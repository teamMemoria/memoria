import { useEffect, useId, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { Icon } from '../../components/Icon'
import {
  Button,
  Panel,
  StatusLabel,
  TextAreaField,
} from '../../components/controls'
import {
  canDecideKnowledge,
  type KnowledgeDraft,
  type KnowledgeReviewApi,
} from '../../types/knowledge'
import type { Viewer } from '../../types/viewer'
import { queueTabFor, queueTabs } from './draftsQueue'

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'unavailable' }
  | { status: 'ready'; entry: KnowledgeDraft; canDecide: boolean }

const decidedAtFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'UTC',
})

const statusTone = {
  pending: 'neutral',
  approved: 'positive',
  flagged: 'attention',
  rejected: 'neutral',
} as const

function DecisionForm({
  api,
  managerId,
  entry,
  onDecided,
}: {
  api: KnowledgeReviewApi
  managerId: string
  entry: KnowledgeDraft
  onDecided: (entry: KnowledgeDraft) => void
}) {
  const verifiedId = useId()
  const reasonId = useId()
  const reference = entry.verificationReference
  const [referenceOpened, setReferenceOpened] = useState(false)
  const [verified, setVerified] = useState(false)
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState<'approve' | 'reject' | null>(null)
  const [failed, setFailed] = useState(false)
  // Permission alone never unlocks approval: the reference must be checked.
  const canApprove = reference !== null && referenceOpened && verified

  async function decide(outcome: 'approve' | 'reject') {
    if (saving) return
    setSaving(outcome)
    setFailed(false)
    try {
      onDecided(
        outcome === 'approve'
          ? await api.approve(managerId, entry.id, reference!.url)
          : await api.reject(managerId, entry.id, reason),
      )
    } catch {
      // Keep the verification and reason so the Manager can try again.
      setFailed(true)
      setSaving(null)
    }
  }

  function reject(event: FormEvent) {
    event.preventDefault()
    if (reason.trim()) void decide('reject')
  }

  return (
    <>
      <section className="knowledge-review-step" aria-labelledby={`${verifiedId}-title`}>
        <h3 id={`${verifiedId}-title`}>Verify and approve</h3>
        {reference ? (
          <>
            <p>
              Check the draft against the authoritative reference before
              approving. Matching conversations do not count as verification.
            </p>
            <a
              className="knowledge-review-reference"
              href={reference.url}
              target="_blank"
              rel="noreferrer"
              onClick={() => setReferenceOpened(true)}
            >
              <Icon name="document" /> Open verification reference:{' '}
              {reference.title}
            </a>
            <label className="knowledge-review-check" htmlFor={verifiedId}>
              <input
                id={verifiedId}
                type="checkbox"
                checked={verified}
                disabled={!referenceOpened || saving !== null}
                onChange={(event) => setVerified(event.target.checked)}
              />
              I checked this draft against {reference.title}
            </label>
          </>
        ) : (
          <p>
            No authoritative reference is available, so this entry cannot be
            approved. Matching conversations alone do not verify it.
          </p>
        )}
        <Button
          loading={saving === 'approve'}
          loadingLabel="Approving…"
          disabled={!canApprove || saving !== null}
          onClick={() => void decide('approve')}
        >
          Approve
        </Button>
      </section>
      <form className="knowledge-review-step" onSubmit={reject}>
        <h3>Reject</h3>
        <TextAreaField
          id={reasonId}
          label="Reason for rejection"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          disabled={saving !== null}
          required
        />
        <Button
          type="submit"
          variant="secondary"
          loading={saving === 'reject'}
          loadingLabel="Rejecting…"
          disabled={!reason.trim() || saving !== null}
        >
          Reject
        </Button>
      </form>
      {failed && (
        <p role="alert">The decision could not be saved. Please try again.</p>
      )}
    </>
  )
}

function DecisionPanel({
  api,
  managerId,
  entry,
  canDecide,
  onDecided,
}: {
  api: KnowledgeReviewApi
  managerId: string
  entry: KnowledgeDraft
  canDecide: boolean
  onDecided: (entry: KnowledgeDraft) => void
}) {
  if (!canDecideKnowledge(entry)) {
    const { decision } = entry
    return (
      <Panel title="Decision" className="knowledge-review-decision">
        <StatusLabel tone={entry.status === 'approved' ? 'positive' : 'neutral'}>
          {entry.status === 'approved' ? 'Approved' : 'Rejected'}
        </StatusLabel>
        {decision ? (
          <p className="metadata-line">
            <span>{decision.managerName}</span>
            <span>{decidedAtFormatter.format(new Date(decision.decidedAt))} UTC</span>
          </p>
        ) : (
          entry.approvedBy && <p>Approved by {entry.approvedBy}</p>
        )}
        {decision?.reason && <p>Reason: {decision.reason}</p>}
        {entry.status === 'approved' && (
          <p>This entry is available on Agent knowledge pages.</p>
        )}
      </Panel>
    )
  }

  if (api.decisionsAvailable === false) {
    return <Panel title="Decision" className="knowledge-review-decision">
      <p>Knowledge drafts are read-only in this demo. Approve and reject are not available yet.</p>
    </Panel>
  }

  return (
    <Panel title="Decision" className="knowledge-review-decision">
      {canDecide ? (
        <DecisionForm
          key={`${entry.id}:${entry.version}:${entry.verificationReference?.url}`}
          api={api}
          managerId={managerId}
          entry={entry}
          onDecided={onDecided}
        />
      ) : (
        <p>You do not have permission to approve or reject knowledge.</p>
      )}
    </Panel>
  )
}

export function KnowledgeReview({
  viewer,
  api,
}: {
  viewer: Viewer
  api: KnowledgeReviewApi | null
}) {
  const { entryId = '' } = useParams()
  const [params] = useSearchParams()
  const search = params.size ? `?${params}` : ''
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    if (!api || viewer.role !== 'manager') return
    void api.getForManager(viewer.id, entryId).then(
      (detail) => {
        if (!active) return
        setState(
          detail && detail.entry.id === entryId
            ? { status: 'ready', ...detail }
            : { status: 'unavailable' },
        )
      },
      () => {
        if (active) setState({ status: 'error' })
      },
    )
    return () => {
      active = false
    }
  }, [api, viewer.id, viewer.role, entryId, attempt])

  if (viewer.role !== 'manager') {
    return (
      <Panel title="Page unavailable for your role">
        <p>Knowledge review is available in the Manager workspace.</p>
      </Panel>
    )
  }

  const back = (
    <Link className="knowledge-drafts-back" to={`/manager/knowledge${search}`}>
      <Icon name="arrowLeft" />
      Knowledge drafts
    </Link>
  )

  if (!api || state.status !== 'ready' || state.entry.id !== entryId) {
    return (
      <div className="knowledge-drafts">
        {back}
        <h1>Knowledge review</h1>
        {!api ? (
          <Panel title="Knowledge review unavailable">
            <p>Knowledge review is not connected.</p>
          </Panel>
        ) : state.status === 'loading' || state.status === 'ready' ? (
          <p role="status">Loading knowledge entry…</p>
        ) : state.status === 'error' ? (
          <Panel title="Unable to load knowledge entry">
            <p role="alert">The entry could not be loaded. Please try again.</p>
            <Button
              onClick={() => {
                setState({ status: 'loading' })
                setAttempt((value) => value + 1)
              }}
            >
              Try again
            </Button>
          </Panel>
        ) : (
          <Panel title="Entry unavailable">
            <p>This knowledge entry is not available for review.</p>
          </Panel>
        )}
      </div>
    )
  }

  const { entry, canDecide } = state
  const tab = queueTabFor(entry)

  return (
    <div className="knowledge-drafts knowledge-review">
      {back}
      <header className="knowledge-review-header">
        <h1>{entry.title}</h1>
        <StatusLabel tone={statusTone[tab]}>{queueTabs[tab]}</StatusLabel>
        <p className="metadata-line">
          <span>{entry.id}</span>
          <span>{entry.topic}</span>
          <span>Version {entry.version.replace(/^v(?=\d)/i, '')}</span>
        </p>
      </header>
      <div className="knowledge-review-columns">
        <div className="knowledge-review-content">
          <section aria-labelledby="knowledge-review-draft">
            <h2 id="knowledge-review-draft">Draft</h2>
            {entry.paragraphs.map((paragraph) => (
              <p key={paragraph}>{paragraph}</p>
            ))}
            {entry.steps.length > 0 && (
              <ol>
                {entry.steps.map((step) => (
                  <li key={step.number} value={step.number}>
                    {step.text}
                  </li>
                ))}
              </ol>
            )}
          </section>
          <section aria-labelledby="knowledge-review-passages">
            <h2 id="knowledge-review-passages">Supporting conversations</h2>
            <p className="metadata-line">
              Found in {entry.sourceConversationIds.length}{' '}
              {entry.sourceConversationIds.length === 1
                ? 'conversation'
                : 'conversations'}
              . These show where the answer came from; they do not verify it.
            </p>
            {entry.passages.length ? (
              <ul className="knowledge-review-passages">
                {entry.passages.map((item) => (
                  <li key={`${item.conversationId}-${item.turnNumber}`}>
                    <span className="metadata-line">
                      <span>Call {item.conversationId}</span>
                      <span>Turn {item.turnNumber}</span>
                      <span>{item.speaker}</span>
                    </span>
                    <blockquote>{item.text}</blockquote>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No conversation passages are available for this entry.</p>
            )}
          </section>
        </div>
        <DecisionPanel
          api={api}
          managerId={viewer.id}
          entry={entry}
          canDecide={canDecide}
          onDecided={(decided) =>
            setState({ status: 'ready', entry: decided, canDecide })
          }
        />
      </div>
    </div>
  )
}
