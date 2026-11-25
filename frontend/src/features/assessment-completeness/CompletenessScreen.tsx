import { useCompleteness } from './controller'
import { Card } from '../../components/ui/card'
import { Icon } from '../../components/Icon'
import {
  Coaching,
  EvidenceLink,
  AssessmentDashboard,
  AssessmentSummary,
  Quote,
  EvidenceSection,
} from '../assessment-shared/AssessmentElements'
import { checkTurns, type ScreenProps } from '../assessment-shared/assessment'
import { ConversationChart } from '../assessment-shared/ConversationChart'
import { ArchivedCompleteness } from './ArchivedCompleteness'
import './completeness.css'

export function CompletenessScreen({ data, onOpen }: ScreenProps) {
  const { requests, promises, unresolved, answered, selected, previewTurns, setSelection, selectResponse } = useCompleteness(data)
  if (data.call.assessmentSource === 'simulation' && !requests.length) {
    return <ArchivedCompleteness data={data} onOpen={onOpen} />
  }

  return (
    <>
      <AssessmentDashboard data={data} category="completeness">
        <Card className="dashboard-card action-area request-coverage">
          <h2>Agent actions</h2>
          {!data.criterion?.scoring && (
            <AssessmentSummary data={data} onOpen={onOpen} />
          )}
          <div className="request-list">
            {requests.map((request, index) => (
              <button
                key={request.id}
                onClick={() => {
                  setSelection(request.id)
                  onOpen([...request.requestTurns, ...request.responseTurns])
                }}
              >
                <span
                  className={`request-icon grid-center ${index % 2 ? 'request-icon--blue' : ''}`}
                >
                  <Icon name="document" size={23} />
                </span>
                <span>
                  <strong className="check-excerpt">{request.text}</strong>
                  <small>
                    Request turns {request.requestTurns.join(', ')}
                    {request.responseTurns.length
                      ? `, response turns ${request.responseTurns.join(', ')}`
                      : ' (response unresolved)'}
                  </small>
                </span>
                <span
                  className={`request-state inline-center request-state--${request.state}`}
                >
                  {request.state}
                  {request.state === 'answered' && <Icon name="check" />}
                </span>
              </button>
            ))}
          </div>
          {unresolved.length > 0 && (
            <details className="request-limitations">
              <summary>{unresolved.length} unresolved checks</summary>
              <p>
                These checks describe limits in the assessment.
              </p>
              {unresolved.map((check) => (
                <div key={check.id}>
                  <p>{check.explanation}</p>
                  <EvidenceLink
                    turns={checkTurns(check)}
                    checkId={check.id}
                    onOpen={onOpen}
                  >
                    {check.requirement}
                  </EvidenceLink>
                </div>
              ))}
            </details>
          )}
          {!requests.length && (
            <p className="card-subtitle">
              No supported request links supplied.
            </p>
          )}
          <div
            className={`promise-note flex-center ${promises.length ? '' : 'promise-note--empty'}`}
          >
            <span className="promise-icon">
              <Icon name="info" size={19} />
            </span>
            <p>
              <strong>
                {promises.length
                  ? `${promises.length} recorded ${promises.length === 1 ? 'promise' : 'promises'}`
                  : 'Promise evidence'}
              </strong>
              <span>
                {promises.length
                  ? 'Promised; completion is not established.'
                  : 'No outstanding promise links supplied.'}
              </span>
            </p>
            {promises.length > 0 && (
              <EvidenceLink
                turns={promises.flatMap((request) => [
                  ...request.requestTurns,
                  ...request.responseTurns,
                ])}
                onOpen={onOpen}
              >
                View promise
              </EvidenceLink>
            )}
          </div>
          <p className="request-boundary">Addressed does not mean completed.</p>
        </Card>
      </AssessmentDashboard>
      <EvidenceSection
        titleId="completeness-evidence-title"
        data={data}
        action={
          <span className="card-badge inline-center">
            {requests.length} recognised requests, {promises.length} promises
          </span>
        }
      >
        <ConversationChart
          turns={data.call.transcript?.turns ?? []}
          events={answered.map(
            (request) =>
              request.responseTurns[request.responseTurns.length - 1],
          )}
          label="Requests with linked answers"
          colour="#16815c"
          selected={selected?.responseTurns.at(-1)}
          onSelect={selectResponse}
        />
        <div className="quote-pair">
          {previewTurns.map((turn) => (
            <Quote key={turn.number} turn={turn} onOpen={onOpen} />
          ))}
        </div>
        <div className="completion-strip flex-center">
          <span>Customer request</span>
          <i />
          <span>
            {selected?.state === 'answered'
              ? 'Linked response'
              : (selected?.state ?? 'Response unresolved')}
          </span>
          <i />
          <span>
            {selected?.responseTurns.length
              ? `Linked turns ${selected.responseTurns.join(', ')}`
              : 'No linked response'}
          </span>
        </div>
      </EvidenceSection>
      <Coaching data={data} />
    </>
  )
}
