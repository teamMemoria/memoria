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
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '../../components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '../../components/ui/dialog'
import {
  canDecideKnowledge,
  type KnowledgeDraft,
  type KnowledgeReviewApi,
} from '../../types/knowledge'
import type { Viewer } from '../../types/viewer'
import { queueTabFor, queueTabs } from './draftsQueue'
import { KnowledgeSources } from './KnowledgeSources'
import './knowledge-drafts.css'

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
  pending: 'attention',
  approved: 'positive',
  flagged: 'attention',
  rejected: 'neutral',
} as const

function SavedDecision({ entry }: { entry: KnowledgeDraft }) {
  const { decision } = entry
  return (
    <>
      <StatusLabel tone={entry.status === 'approved' ? 'positive' : 'neutral'}>
        {entry.status === 'approved' ? 'Approved' : 'Rejected'}
      </StatusLabel>
      {decision ? (
        <p className="metadata-line">
          <span>{decision.managerName}</span>
          <span>
            {decidedAtFormatter.format(new Date(decision.decidedAt))} UTC
          </span>
        </p>
      ) : (
        entry.approvedBy && <p>Approved by {entry.approvedBy}</p>
      )}
      {decision?.reason && <p>Reason: {decision.reason}</p>}
      {entry.status === 'approved' && (
        <p>This entry is available on Agent knowledge pages.</p>
      )}
    </>
  )
}

function ReviewContent({
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
  const verifiedId = useId()
  const reasonId = useId()
  const reference = entry.verificationReference
  const [referenceOpened, setReferenceOpened] = useState(false)
  const [verified, setVerified] = useState(false)
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState<'approve' | 'reject' | null>(null)
  const [failed, setFailed] = useState<'approve' | 'reject' | null>(null)
  canDecide = canDecide && api.decisionsAvailable !== false
  const needsDecision = canDecideKnowledge(entry)
  const canApprove =
    reference !== null &&
    referenceOpened &&
    verified &&
    !entry.duplicateOfId &&
    !entry.possibleConflicts?.length
  const tab = queueTabFor(entry)

  async function decide(outcome: 'approve' | 'reject') {
    if (saving || !canDecide || !needsDecision) return
    if (outcome === 'approve' && !canApprove) return
    if (outcome === 'reject' && !reason.trim()) return
    setSaving(outcome)
    setFailed(null)
    try {
      onDecided(
        outcome === 'approve'
          ? await api.approve(
              managerId,
              entry.id,
              reference!.url,
              entry.version,
            )
          : await api.reject(managerId, entry.id, reason, entry.version),
      )
    } catch {
      setFailed(outcome)
      setSaving(null)
    }
  }

  function reject(event: FormEvent) {
    event.preventDefault()
    void decide('reject')
  }

  return (
    <>
      <header className="knowledge-review-header">
        <div className="knowledge-review-title">
          <h1>{entry.title}</h1>
          <StatusLabel tone={statusTone[tab]}>{queueTabs[tab]}</StatusLabel>
        </div>
        <p className="metadata-line">
          <span>
            {entry.sourceConversationIds.length} source{' '}
            {entry.sourceConversationIds.length === 1
              ? 'conversation'
              : 'conversations'}
          </span>
          <span>
            {entry.id} · {entry.topic} · Version{' '}
            {entry.version.replace(/^v(?=\d)/i, '')}
          </span>
        </p>
      </header>
      {api.decisionsAvailable === false && <Panel title="Decision">
        <p>Knowledge drafts are read-only in this demo. Approve and reject are not available yet.</p>
      </Panel>}
      <KnowledgeSources entry={entry} />
      <Panel title="Knowledge entry" className="knowledge-entry">
        {reference && (
          <a
            className="knowledge-review-reference"
            href={reference.url}
            target="_blank"
            rel="noreferrer"
            aria-label={`Open verification reference: ${reference.title}`}
            onClick={() => setReferenceOpened(true)}
          >
            <Icon name="link" /> Verification source
          </a>
        )}
        <div className="knowledge-entry-text">
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
          {!entry.paragraphs.length && !entry.steps.length && (
            <p>No draft content is available.</p>
          )}
        </div>
        {needsDecision && canDecide && reference && (
          <Collapsible className="knowledge-verification">
            <CollapsibleTrigger asChild>
              <Button variant="secondary">
                <Icon name="plus" /> Verify reference
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="knowledge-verification-content">
              <h3>Verify and approve</h3>
              <p>
                Check the draft against the authoritative reference before
                approving. Matching conversations do not count as verification.
              </p>
              <p className="metadata-line">
                Verification reference: {reference.title}
              </p>
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
            </CollapsibleContent>
          </Collapsible>
        )}
        <p className="metadata-line">
          {reference
            ? 'Review the verification source before approving. Source calls show examples, not policy authority.'
            : 'No authoritative reference is available, so this entry cannot be approved. Matching conversations alone do not verify it.'}
        </p>
      </Panel>
      <Panel title="Decision" className="knowledge-review-decision">
        {entry.duplicateOfId && (
          <p>Resolve duplicate draft {entry.duplicateOfId} before approval.</p>
        )}
        {entry.possibleConflicts?.map((conflict) => (
          <p key={conflict.id}>Unresolved conflict: {conflict.explanation}</p>
        ))}
        {!needsDecision ? (
          <SavedDecision entry={entry} />
        ) : !canDecide ? (
          <p>You do not have permission to approve or reject knowledge.</p>
        ) : (
          <>
            <div className="knowledge-review-actions">
              <Button
                loading={saving === 'approve'}
                loadingLabel="Approving…"
                disabled={!canApprove || saving !== null}
                onClick={() => void decide('approve')}
              >
                Approve
              </Button>
              <Dialog>
                <DialogTrigger asChild>
                  <Button
                    variant="secondary"
                    className="knowledge-review-reject"
                    disabled={saving !== null}
                  >
                    Reject
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogTitle>Reject knowledge draft</DialogTitle>
                  <DialogDescription>
                    A reason is required. Rejected guidance will remain
                    unavailable to Agents.
                  </DialogDescription>
                  <form className="knowledge-review-step" onSubmit={reject}>
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
                    {failed === 'reject' && (
                      <p role="alert">
                        The decision could not be saved. Please try again.
                      </p>
                    )}
                  </form>
                </DialogContent>
              </Dialog>
            </div>
            {failed === 'approve' && (
              <p role="alert">
                The decision could not be saved. Please try again.
              </p>
            )}
          </>
        )}
      </Panel>
    </>
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
      <Icon name="arrowLeft" /> Knowledge drafts
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
  return (
    <div className="knowledge-drafts knowledge-review">
      {back}
      <ReviewContent
        key={`${entry.id}:${entry.version}:${entry.verificationReference?.url}`}
        api={api}
        managerId={viewer.id}
        entry={entry}
        canDecide={canDecide}
        onDecided={(decided) =>
          setState({ status: 'ready', entry: decided, canDecide })
        }
      />
    </div>
  )
}
