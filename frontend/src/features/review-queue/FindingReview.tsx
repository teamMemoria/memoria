import { useEffect, useId, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { ApprovedReference } from '../../components/ApprovedReference'
import { Icon } from '../../components/Icon'
import {
  Button,
  Panel,
  SelectField,
  StatusLabel,
  TextAreaField,
} from '../../components/controls'
import {
  auditResults,
  type AuditResult,
  type CallFinding,
  type CallReview,
} from '../../types/callReview'
import type { Viewer } from '../../types/viewer'
import {
  decisionOutcomes,
  type DecisionInput,
  type ManagerDecision,
  type TeamReviewApi,
} from './teamQueue'

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'unavailable' }
  | { status: 'ready'; call: CallReview; canDecide: boolean }

const decidedAtFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'UTC',
})

function SavedDecision({ decision }: { decision: ManagerDecision }) {
  return (
    <>
      <StatusLabel tone={
        decision.outcome === 'cannot-assess' ? 'neutral'
          : decision.outcome === 'confirmed' ? 'attention' : 'positive'
      }>
        {decisionOutcomes[decision.outcome].label}
      </StatusLabel>
      <div className="finding-review-field">
        <h3>Reason</h3>
        <p>{decision.reason}</p>
      </div>
      <div className="finding-review-field">
        <h3>Feedback for the agent</h3>
        <p>{decision.feedback}</p>
      </div>
      <p className="metadata-line">
        <span>{decision.managerName}</span>
        <span>{decidedAtFormatter.format(new Date(decision.decidedAt))} UTC</span>
      </p>
      <p>The agent can read this decision and feedback on their call.</p>
    </>
  )
}

function DecisionForm({
  onSave,
}: {
  onSave: (decision: DecisionInput) => Promise<void>
}) {
  const id = useId()
  const [outcome, setOutcome] = useState<DecisionInput['outcome'] | null>(null)
  const [reviewedResult, setReviewedResult] = useState<AuditResult | ''>('')
  const [reason, setReason] = useState('')
  const [feedback, setFeedback] = useState('')
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)
  const corrected = outcome === 'corrected'
  const complete =
    outcome !== null &&
    (!corrected || reviewedResult !== '') &&
    reason.trim() !== '' &&
    feedback.trim() !== ''

  async function save(event: FormEvent) {
    event.preventDefault()
    if (saving || !complete) return
    setSaving(true)
    setFailed(false)
    try {
      await onSave(
        corrected && reviewedResult !== ''
          ? { outcome, reviewedResult, reason, feedback }
          : { outcome, reason, feedback },
      )
    } catch {
      // Nothing is shown as saved; the form keeps what was entered.
      setFailed(true)
      setSaving(false)
    }
  }

  return (
    <form className="finding-review-form" onSubmit={save}>
      <fieldset disabled={saving}>
        <legend>Outcome</legend>
        {Object.entries(decisionOutcomes).map(([value, option]) => (
          <label key={value} className="finding-review-option" htmlFor={`${id}-${value}`}>
            <input
              id={`${id}-${value}`}
              type="radio"
              name={`${id}-outcome`}
              value={value}
              checked={outcome === value}
              onChange={() => setOutcome(value as DecisionInput['outcome'])}
            />
            <span>
              <strong>{option.label}</strong>
              <span className="metadata-line">{option.description}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {corrected && (
        <SelectField
          id={`${id}-reviewed-result`}
          label="Corrected result"
          value={reviewedResult}
          onChange={(event) => setReviewedResult(event.target.value as AuditResult | '')}
          disabled={saving}
          required
        >
          <option value="">Choose the correct result</option>
          {Object.entries(auditResults).map(([value, result]) => (
            <option key={value} value={value}>
              {result.label}
            </option>
          ))}
        </SelectField>
      )}
      <TextAreaField
        id={`${id}-reason`}
        label="Reason for this decision"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        disabled={saving}
        required
      />
      <TextAreaField
        id={`${id}-feedback`}
        label="Feedback for the agent"
        value={feedback}
        onChange={(event) => setFeedback(event.target.value)}
        disabled={saving}
        required
      />
      {failed && (
        <p role="alert">The decision could not be saved. Please try again.</p>
      )}
      <Button type="submit" loading={saving} loadingLabel="Saving…" disabled={!complete}>
        Save decision
      </Button>
    </form>
  )
}

function Evidence({ call, finding }: { call: CallReview; finding: CallFinding }) {
  const turns = call.transcript?.turns ?? []
  const reference = call.references.find((entry) => entry.id === finding.referenceId)
  const approved = reference?.status === 'approved'

  return (
    <div className="finding-review-evidence">
      <section aria-labelledby="finding-review-transcript">
        <h2 id="finding-review-transcript">Transcript</h2>
        {!call.transcript?.complete && (
          <p className="metadata-line">
            {call.transcript?.unavailableReason ?? 'The complete conversation is unavailable.'}{' '}
            Missing evidence does not establish an agent error.
          </p>
        )}
        {turns.length ? (
          <ol className="finding-review-turns">
            {turns.map((turn) => (
              <li
                key={turn.number}
                value={turn.number}
                data-evidence={finding.evidenceTurnNumbers.includes(turn.number)}
              >
                <span className="metadata-line">
                  <span>Turn {turn.number}</span>
                  <span>{turn.speaker}</span>
                  {turn.time && <span>{turn.time}</span>}
                  {finding.evidenceTurnNumbers.includes(turn.number) && <span>Cited</span>}
                </span>
                <span>{turn.text}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p>The transcript is unavailable.</p>
        )}
      </section>
      <section aria-labelledby="finding-review-reference">
        <h2 id="finding-review-reference">Approved reference</h2>
        {reference && approved ? (
          <ApprovedReference entry={reference} highlightStep={finding.referenceStep} />
        ) : (
          <p>No approved reference applies to this finding.</p>
        )}
      </section>
    </div>
  )
}

export function FindingReview({
  viewer,
  api,
}: {
  viewer: Viewer
  api: TeamReviewApi | null
}) {
  const { conversationId = '', findingId = '' } = useParams()
  const [params] = useSearchParams()
  const search = params.size ? `?${params}` : ''
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    if (!api || viewer.role !== 'manager') return
    void api.getCallForManager(viewer.id, conversationId).then(
      (detail) => {
        if (!active) return
        setState(
          detail && detail.call.id === conversationId
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
  }, [api, viewer.id, viewer.role, conversationId, attempt])

  if (viewer.role !== 'manager') {
    return (
      <Panel title="Page unavailable for your role">
        <p>Finding review is available in the Manager workspace.</p>
      </Panel>
    )
  }

  const back = (
    <Link className="review-queue-back" to={`/manager/conversations${search}`}>
      <Icon name="arrowLeft" />
      Team conversations
    </Link>
  )
  const finding =
    state.status === 'ready'
      ? state.call.findings.find((item) => item.id === findingId)
      : undefined

  if (!api || state.status !== 'ready' || !finding) {
    return (
      <div className="review-queue">
        {back}
        <h1>Finding review</h1>
        {!api ? (
          <Panel title="Team review unavailable">
            <p>Team review data is not connected.</p>
          </Panel>
        ) : state.status === 'loading' ? (
          <p role="status">Loading finding…</p>
        ) : state.status === 'error' ? (
          <Panel title="Unable to load finding">
            <p role="alert">The finding could not be loaded. Please try again.</p>
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
          <Panel title="Finding unavailable">
            <p>This finding is not available for review.</p>
          </Panel>
        )}
      </div>
    )
  }

  const { call, canDecide } = state
  const flagged = call.reviewRequest?.findingId === finding.id

  async function saveDecision(decision: DecisionInput) {
    const saved = await api!.saveDecision(viewer.id, call.id, finding!.id, decision)
    setState({
      status: 'ready',
      canDecide,
      call: {
        ...call,
        decision: saved,
        reviewRequest: call.reviewRequest && { ...call.reviewRequest, status: 'complete' },
      },
    })
  }

  return (
    <div className="review-queue finding-review">
      {back}
      <header className="finding-review-header">
        <h1>{finding.title}</h1>
        <Link to={`/manager/conversations/${encodeURIComponent(call.id)}/assessments/${finding.criterionId}${search}`}>Open {finding.criterionId} assessment</Link>
        <p className="metadata-line">
          <span>Call {call.id}</span>
          <span>{call.agentName}</span>
          <span>{call.topic}</span>
        </p>
      </header>
      <div className="finding-review-columns">
        <div className="finding-review-main">
          <Panel title="Automatic assessment" className="finding-review-original">
            <p className="metadata-line">
              Original automatic feedback. A Manager decision does not change it.
            </p>
            <p>{finding.explanation}</p>
            <p>Suggested next step: {finding.suggestion}</p>
          </Panel>
          <Evidence call={call} finding={finding} />
        </div>
        <div className="finding-review-side">
          <Panel title="Agent input">
            <div className="finding-review-field">
              <h3>Flag reason</h3>
              <p>{flagged ? call.reviewRequest!.reason : 'This finding was not flagged.'}</p>
            </div>
            <div className="finding-review-field">
              <h3>Agent context</h3>
              <p>{call.agentContext?.text ?? 'The agent did not add context.'}</p>
            </div>
          </Panel>
          <Panel title="Manager decision">
            {call.decision ? (
              <SavedDecision decision={call.decision} />
            ) : !canDecide ? (
              <p>You do not have permission to save review decisions.</p>
            ) : !flagged || call.reviewRequest?.status !== 'requested' ? (
              <p>This finding has no open review request.</p>
            ) : (
              <DecisionForm onSave={saveDecision} />
            )}
          </Panel>
        </div>
      </div>
    </div>
  )
}
