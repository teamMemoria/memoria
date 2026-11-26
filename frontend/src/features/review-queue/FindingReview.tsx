import { useSubmission } from '../../lib/useSubmission'
import { formatTimestamp } from '../../lib/dates'
import { ResourceNotice } from '../../components/ResourceNotice'
import { transcriptEvidence } from '../../lib/transcriptEvidence'
import { TranscriptNotice } from '../../components/TranscriptNotice'
import { useCallReview } from '../../lib/useCallReview'
import { useId, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { ApprovedReference } from '../../components/ApprovedReference'
import { BackLink } from '../../components/BackLink'
import {
  Button,
  Panel,
  SelectField,
  StatusLabel,
  TextAreaField,
} from '../../components/controls'
import {
  auditResults,
  decisionOutcomes,
  type AuditResult,
  type CallFinding,
  type CallReview,
} from '../../types/callReview'
import type { Viewer } from '../../types/viewer'
import {
  type DecisionInput,
  type ManagerDecision,
  type TeamReviewApi,
} from './teamQueue'

function FindingField({ label, value }: { label: string; value: string }) {
  return <div className="finding-review-field"><h3>{label}</h3><p>{value}</p></div>
}

function SavedDecision({ decision }: { decision: ManagerDecision }) {
  return (
    <>
      <StatusLabel tone={
        decision.outcome === 'cannot-assess' ? 'neutral'
          : decision.outcome === 'confirmed' ? 'attention' : 'positive'
      }>
        {decisionOutcomes[decision.outcome].label}
      </StatusLabel>
      <FindingField label="Reason" value={decision.reason} />
      <FindingField label="Feedback for the agent" value={decision.feedback} />
      <p className="metadata-line">
        <span>{decision.managerName}</span>
        <span>{formatTimestamp(decision.decidedAt)}</span>
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
  const { submit, saving, failed } = useSubmission()
  const corrected = outcome === 'corrected'
  const complete =
    outcome !== null &&
    (!corrected || reviewedResult !== '') &&
    reason.trim() !== '' &&
    feedback.trim() !== ''

  function save(event: FormEvent) {
    event.preventDefault()
    if (!complete) return
    void submit(true, () => onSave(
      corrected && reviewedResult !== ''
        ? { outcome, reviewedResult, reason, feedback }
        : { outcome, reason, feedback },
    ))
  }

  return (
    <form className="finding-review-form" onSubmit={save}>
      <fieldset disabled={Boolean(saving)}>
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
          disabled={Boolean(saving)}
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
      {[
        { name: 'reason', label: 'Reason for this decision', value: reason, update: setReason },
        { name: 'feedback', label: 'Feedback for the agent', value: feedback, update: setFeedback },
      ].map(({ name, label, value, update }) => (
        <TextAreaField key={name} id={`${id}-${name}`} label={label} value={value}
          onChange={(event) => update(event.target.value)} disabled={Boolean(saving)} required />
      ))}
      {failed && (
        <p role="alert">The decision could not be saved. Please try again.</p>
      )}
      <Button type="submit" loading={Boolean(saving)} loadingLabel="Saving…" disabled={!complete}>
        Save decision
      </Button>
    </form>
  )
}

function Evidence({ call, finding }: { call: CallReview; finding: CallFinding }) {
  const { turns, selected } = transcriptEvidence(call.transcript, finding.evidenceTurnNumbers, 'full')
  const reference = call.references.find((entry) => entry.id === finding.referenceId)
  const approved = reference?.status === 'approved'

  return (
    <div className="finding-review-evidence">
      <section aria-labelledby="finding-review-transcript">
        <h2 id="finding-review-transcript">Transcript</h2>
        <TranscriptNotice transcript={call.transcript} className="metadata-line" managerReview />
        {turns.length ? (
          <ol className="finding-review-turns">
            {turns.map((turn) => (
              <li
                key={turn.number}
                value={turn.number}
                data-evidence={selected.has(turn.number)}
              >
                <span className="metadata-line">
                  <span>Turn {turn.number}</span>
                  <span>{turn.speaker}</span>
                  {turn.time && <span>{turn.time}</span>}
                  {selected.has(turn.number) && <span>Cited</span>}
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
  const state = useCallReview(null, viewer.id, conversationId, api)

  const back = (
    <BackLink to={`/manager/conversations${search}`}>Team conversations</BackLink>
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
        ) : (
          <ResourceNotice state={state} loading="Loading finding…" errorTitle="Unable to load finding"
            error="The finding could not be loaded. Please try again."
            unavailableTitle="Finding unavailable" unavailable="This finding is not available for review." />
        )}
      </div>
    )
  }

  const { call, canDecide } = state
  const flagged = call.reviewRequest?.findingId === finding.id

  async function saveDecision(decision: DecisionInput) {
    const saved = await api!.saveDecision(viewer.id, call.id, finding!.id, decision)
    if (state.status === 'ready') {
      state.update({
        decision: saved,
        reviewRequest: call.reviewRequest && { ...call.reviewRequest, status: 'complete' },
      })
    }
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
            <FindingField label="Flag reason"
              value={flagged ? call.reviewRequest!.reason : 'This finding was not flagged.'} />
            <FindingField label="Agent context"
              value={call.agentContext?.text ?? 'The agent did not add context.'} />
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
