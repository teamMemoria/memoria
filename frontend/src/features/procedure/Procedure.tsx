import { conversationFilters } from '../../lib/workspaceSearch'
import { ResourceNotice } from '../../components/ResourceNotice'
import { transcriptEvidence } from '../../lib/transcriptEvidence'
import { useEffect, useRef } from 'react'
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router'
import { ApprovedReference } from '../../components/ApprovedReference'
import { Button, Panel } from '../../components/controls'
import { Icon } from '../../components/Icon'
import { useCallReview } from '../../lib/useCallReview'
import type {
  CallApi,
  CallReview,
  TranscriptTurn,
} from '../../types/callReview'
import { canReadKnowledge } from '../../types/knowledge'
import type { Viewer } from '../../types/viewer'
import {
  reviewRequestStatuses,
  reviewStatusLabels,
} from '../conversations/conversations'
import { AgentReviewForms } from './AgentReviewForms'
import './procedure.css'

function TranscriptTable({
  turns,
  selected,
  onSelect,
  scrollOnMount = false,
}: {
  turns: TranscriptTurn[]
  selected: number | null
  onSelect: (turn: number) => void
  scrollOnMount?: boolean
}) {
  const selectedRow = useRef<HTMLTableRowElement>(null)
  const previousSelection = useRef(scrollOnMount ? undefined : selected)

  useEffect(() => {
    if (previousSelection.current !== selected) {
      selectedRow.current?.scrollIntoView?.({ block: 'nearest' })
    }
    previousSelection.current = selected
  }, [selected])

  return (
    <table className="evidence-transcript">
      <caption className="sr-only">
        Numbered conversation turns
      </caption>
      <thead>
        <tr>
          <th scope="col">#</th>
          <th scope="col">Speaker</th>
          <th scope="col">Message</th>
          <th scope="col">Time</th>
        </tr>
      </thead>
      <tbody>
        {turns.map((turn) => (
          <tr
            key={turn.number}
            id={`transcript-turn-${turn.number}`}
            ref={turn.number === selected ? selectedRow : undefined}
            data-selected={turn.number === selected}
          >
            <td>
              <button
                type="button"
                className="evidence-turn-button"
                aria-label={`Select turn ${turn.number}`}
                aria-pressed={turn.number === selected}
                onClick={() => onSelect(turn.number)}
              >
                {turn.number}
              </button>
            </td>
            <td>{turn.speaker}</td>
            <td>{turn.text}</td>
            <td>{turn.time ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ReferenceDialog({
  call,
  referenceId,
  step,
  agentId,
  onClose,
}: {
  call: CallReview
  referenceId: string | null
  step: number | null
  agentId: string
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const reference = call.references.find((entry) => entry.id === referenceId)
  const readable = reference && canReadKnowledge(reference, agentId)

  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  return (
    <dialog
      ref={dialog}
      className="evidence-reference-dialog panel-frame"
      aria-labelledby="evidence-reference-title"
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) dialog.current?.close()
      }}
    >
      <h2 id="evidence-reference-title">
        {readable ? reference.title : 'Approved reference unavailable'}
      </h2>
      {readable ? (
        <ApprovedReference entry={reference} highlightStep={step} />
      ) : (
        <div className="evidence-unavailable">
          <p>
            {reference?.status === 'stale'
              ? 'This reference is stale and cannot support the finding until it is confirmed again.'
              : reference?.status === 'disputed'
                ? 'This reference is disputed and cannot support the finding while it is under review.'
                : 'An applicable approved reference is not available in your workspace.'}
          </p>
          <p>
            Cannot assess. Missing evidence does not establish an agent error.
          </p>
        </div>
      )}
      <Button
        variant="secondary"
        onClick={() => dialog.current?.close()}
        autoFocus
      >
        Close
      </Button>
    </dialog>
  )
}

export function Procedure({
  viewer,
  api,
}: {
  viewer: Viewer
  api: CallApi | null
}) {
  const { conversationId = '', findingId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const state = useCallReview(api, viewer.id, conversationId)
  const backParams = conversationFilters(params, false)
  const search = backParams.size ? `?${backParams}` : ''
  const overviewPath = `/agent/conversations/${encodeURIComponent(conversationId)}${search}`
  const back = (
    <Link className="evidence-back inline-center" to={overviewPath}>
      Call overview
    </Link>
  )

  if (state.status !== 'ready') {
    return (
      <div className="procedure">
        {back}
        <h1>Conversation evidence</h1>
        <ResourceNotice state={state} loading="Loading conversation evidence…" errorTitle="Unable to load evidence"
          error="Conversation evidence could not be loaded. Please try again."
          unavailableTitle="Conversation unavailable" unavailable="This conversation is not available in your workspace." />
      </div>
    )
  }

  const { call } = state
  const finding = findingId
    ? call.findings.find((item) => item.id === findingId)
    : null
  const turns = call.transcript?.turns ?? []
  const fullTranscript = !findingId
  const requestedTurn = Number(params.get('turn'))
  const selected = turns.some((turn) => turn.number === requestedTurn)
    ? requestedTurn
    : (finding?.evidenceTurnNumbers.find((number) =>
        turns.some((turn) => turn.number === number),
      ) ??
      turns[0]?.number ??
      null)
  const requestedReference = params.get('reference')
  const referenceId = finding
    ? finding.referenceId
    : requestedReference !== null
      ? call.criteria.some(
          (criterion) => criterion.referenceId === requestedReference,
        )
        ? requestedReference
        : null
      : (call.criteria.find((criterion) => criterion.referenceId)
          ?.referenceId ?? null)
  const reference = call.references.find((entry) => entry.id === referenceId)
  const approved = reference && canReadKnowledge(reference, viewer.id)
  const cited = finding?.evidenceTurnNumbers ?? []
  const { missing: missingTurns } = transcriptEvidence(call.transcript, cited)
  const missingEvidence = !call.transcript?.complete || missingTurns.length > 0
  const evidenceLimitation = !call.transcript?.complete
    ? (call.transcript?.unavailableReason ??
      'The complete conversation is unavailable.')
    : missingTurns.length > 0
      ? `Cited transcript ${missingTurns.length === 1 ? 'turn' : 'turns'} ${missingTurns.join(', ')} ${missingTurns.length === 1 ? 'is' : 'are'} unavailable.`
      : 'An applicable approved reference is unavailable, disputed or stale.'
  const { turns: visibleTurns } = transcriptEvidence(
    call.transcript, [...cited, selected ?? 0, 10], fullTranscript ? 'full' : 'selected',
  )
  const transcriptParams = new URLSearchParams(params)
  if (selected) transcriptParams.set('turn', String(selected))
  const transcriptPath = `/agent/conversations/${encodeURIComponent(call.id)}/transcript?${transcriptParams}`

  function selectTurn(number: number) {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        next.set('turn', String(number))
        return next
      },
      { replace: true },
    )
  }

  function closeReference() {
    void navigate(`${location.pathname}${location.search}`, { replace: true })
  }

  if ((!fullTranscript && call.status !== 'ready') || (findingId && !finding)) {
    return (
      <div className="procedure">
        {back}
        <h1>
          {call.status === 'processing'
            ? 'Feedback is processing'
            : call.status === 'unavailable' ? 'Assessment unavailable' : 'Finding unavailable'}
        </h1>
        <p>
          {call.status === 'processing'
            ? 'Automatic feedback is not ready for this call.'
            : call.status === 'unavailable' ? 'No assessment is stored for this conversation.' : 'This finding is not available for this conversation.'}
        </p>
      </div>
    )
  }

  return (
    <div className="procedure">
      {back}
      <header className="evidence-heading">
        <h1>
          {fullTranscript
            ? call.transcript?.complete ? 'Complete conversation' : 'Available transcript'
            : `${call.criteria.find((criterion) => criterion.id === finding?.criterionId)?.title ?? 'Audit'} finding`}
        </h1>
        <div className="metadata-line" role="group" aria-label="Call details">
          <span>{call.assessmentSource === 'simulation' ? `ABCD ${call.sourceId}` : `Call ${call.id}`}</span>
          {fullTranscript ? (
            <>
              <span>{call.agentName}</span>
              <span>{turns.length} turns</span>
            </>
          ) : (
            <>
              <span>Automatic feedback</span>
              <span>Turns 8–15</span>
            </>
          )}
        </div>
      </header>
      {(missingEvidence || (!fullTranscript && !approved)) && (
        <Panel title="Cannot assess">
          <p>{evidenceLimitation}</p>
          <p>Missing evidence does not establish an agent error.</p>
        </Panel>
      )}
      <div
        className={
          fullTranscript ? 'evidence-full-transcript' : 'evidence-columns'
        }
      >
        <section
          className="evidence-panel panel-frame"
          aria-labelledby="conversation-evidence-title"
        >
          <h2 id="conversation-evidence-title">
            {fullTranscript
              ? 'Conversation transcript'
              : 'Conversation evidence'}
          </h2>
          {visibleTurns.length ? (
            <TranscriptTable
              turns={visibleTurns}
              selected={selected}
              onSelect={selectTurn}
              scrollOnMount={fullTranscript && params.has('turn')}
            />
          ) : (
            <p>
              The transcript passage is unavailable. It cannot establish an
              agent error.
            </p>
          )}
        </section>
        {finding && (
          <section
            className="evidence-panel panel-frame evidence-finding"
            aria-labelledby="automatic-feedback-title"
          >
            <h2 id="automatic-feedback-title">Automatic feedback</h2>
            <p>{finding.title}</p>
            <h3>{approved ? 'Required order' : 'Procedure evidence'}</h3>
            {approved && (
              <p className="metadata-line">
                <span>Procedure {reference.id}</span>
                <span>Version {reference.version.replace(/^v(?=\d)/i, '')}</span>
              </p>
            )}
            <div className="evidence-procedure">
              <span className="evidence-procedure-order" aria-hidden="true" />
              <ol className="evidence-procedure-steps">
                {finding.procedureSteps.map((step) => {
                  const target = step.turnNumbers.find((number) =>
                    turns.some((turn) => turn.number === number),
                  )
                  const observed =
                    step.status === 'observed' && target !== undefined
                  return (
                    <li key={step.label}>
                      <span
                        className={`evidence-step-marker grid-center${observed ? '' : ' evidence-step-marker--neutral'}`}
                      >
                        <Icon name={observed ? 'check' : 'info'} />
                      </span>
                      <span>{step.label}</span>
                      <span
                        className={`evidence-step-status${observed ? '' : ' evidence-step-status--neutral'}`}
                      >
                        {observed
                          ? 'Observed'
                          : step.status === 'not-visible'
                            ? 'Not visible in transcript'
                            : 'Cannot assess'}
                      </span>
                      {target ? (
                        <button
                          className="evidence-step-link"
                          type="button"
                          onClick={() => selectTurn(target)}
                          aria-controls={`transcript-turn-${target}`}
                        >
                          Turn {target}
                          {step.note && (
                            <span className="metadata-note">{step.note}</span>
                          )}
                        </button>
                      ) : (
                        <span className="evidence-reference-meta">
                          Evidence unavailable
                        </span>
                      )}
                    </li>
                  )
                })}
              </ol>
            </div>
            <div className="evidence-reference-links">
              <button
                type="button"
                onClick={(event) => {
                  event.currentTarget.focus()
                  void navigate(
                    `${location.pathname}${location.search}#approved-reference`,
                    { replace: true },
                  )
                }}
              >
                <Icon name="document" />{' '}
                {reference
                  ? finding.referenceStep !== null
                    ? `View step ${finding.referenceStep} of ${reference.id}`
                    : `View reference ${reference.id}`
                  : 'Approved reference'}
              </button>
              <Link to={transcriptPath}>
                <Icon name="document" /> Complete transcript
              </Link>
            </div>
            <p className="evidence-suggestion">
              <Icon name="info" />
              {approved && !missingEvidence
                ? `Suggested next step: ${finding.suggestion}`
                : 'Review the missing evidence before drawing a conclusion about the agent.'}
            </p>
          </section>
        )}
      </div>
      {finding && api && <AgentReviewForms api={api} call={call} findingId={finding.id} update={state.update} />}
      <footer className="evidence-footer flex-center">
        <p>
          {fullTranscript
            ? `${turns.length} ${call.transcript?.complete ? 'complete conversation' : 'available'} turns`
            : reviewStatusLabels[
                call.reviewRequest
                  ? reviewRequestStatuses[call.reviewRequest.status]
                  : 'feedback-ready'
              ]}
        </p>
        {!fullTranscript && (
          <Button variant="secondary" disabled>
            Next
          </Button>
        )}
      </footer>
      {location.hash === '#approved-reference' && (
        <ReferenceDialog
          call={call}
          referenceId={referenceId}
          step={finding?.referenceStep ?? null}
          agentId={viewer.id}
          onClose={closeReference}
        />
      )}
    </div>
  )
}
