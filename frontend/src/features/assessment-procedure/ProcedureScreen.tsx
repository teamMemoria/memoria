import { useProcedure } from './controller'
import { ConversationChart } from '../assessment-shared/ConversationChart'
import { Icon } from '../../components/Icon'
import { Card } from '../../components/ui/card'
import {
  Coaching,
  AssessmentDashboard,
  EvidenceLink,
  AssessmentSummary,
  CheckList,
  EvidenceSection,
  Quote,
} from '../assessment-shared/AssessmentElements'
import {
  checkLabels,
  checkTitle,
  type ScreenProps,
} from '../assessment-shared/assessment'
import './procedure.css'

export function ProcedureScreen({ data, onOpen }: ScreenProps) {
  const { featured, linked, selected, actions, activeTurn, steps, setActiveNumber } = useProcedure(data)
  const hasDeduction = featured?.outcome === 'partial' || featured?.outcome === 'breach'
  const hasFeaturedReference = featured?.citations.some(
    (citation) => citation.kind === 'reference',
  )

  return (
    <>
      <AssessmentDashboard data={data} category="procedure">
        <Card className={`dashboard-card finding-card${hasDeduction ? ' finding-card--attention' : ''}`}>
          <div className="card-eyebrow flex-center">
            {featured ? 'Finding' : 'Assessment'}
            {featured && (
              <span className={`card-badge inline-center procedure-finding-status--${featured.outcome}`}>
                {checkLabels[featured.outcome]}
              </span>
            )}
          </div>
          {featured ? (
            <>
              <h2>{checkTitle(featured)}</h2>
              <p className="card-subtitle check-excerpt">
                {featured.explanation}
              </p>
            </>
          ) : (
            <AssessmentSummary data={data} onOpen={onOpen} />
          )}
          {linked.length > 0 && (
            <div className="procedure-finding-quotes">
              {linked.slice(0, 2).map((turn) => (
                <Quote key={turn.number} turn={turn} onOpen={onOpen} />
              ))}
            </div>
          )}
          {featured && (
            <div className="procedure-card-links">
              <EvidenceLink turns={selected} checkId={featured.id} onOpen={onOpen}>
                Compare evidence
              </EvidenceLink>
            </div>
          )}
        </Card>
        <Card className="dashboard-card action-area">
          <h2>Agent actions</h2>
          {data.criterion?.scoring ? (
            <CheckList checks={data.checks} onOpen={onOpen} showExplanations={false} />
          ) : (
            <div className="procedure-checks">
              {steps.map((step, index) => (
                <div className="check-row flex-center" key={index}>
                  <span>
                    <strong>{step.label}</strong>
                    <small>{step.note}</small>
                  </span>
                  <span>
                    {step.status === 'observed'
                      ? 'Observed'
                      : step.status === 'not-visible'
                        ? 'Not visible'
                        : 'Unresolved'}
                  </span>
                  <EvidenceLink turns={step.turnNumbers} onOpen={onOpen}>
                    View evidence
                  </EvidenceLink>
                </div>
              ))}
            </div>
          )}
          {(hasFeaturedReference || data.referenceIds.length > 0) && (
            <div className="procedure-card-links">
              {hasFeaturedReference && (
                <EvidenceLink turns={[]} checkId={featured.id} onOpen={onOpen}>
                  Procedure reference
                </EvidenceLink>
              )}
              {data.referenceIds.map((id) => (
                <EvidenceLink key={id} turns={[]} referenceId={id} onOpen={onOpen}>
                  Reference {id}
                </EvidenceLink>
              ))}
            </div>
          )}
        </Card>
      </AssessmentDashboard>
      <EvidenceSection titleId="procedure-evidence-title" data={data}>
        <ConversationChart
          turns={data.call.transcript?.turns ?? []}
          events={actions.map((turn) => turn.number)}
          label="Recorded actions"
          colour="#365eaa"
          selected={activeTurn?.number}
          onSelect={setActiveNumber}
        />
        <div className="event-timeline">
          {actions.map((turn) => {
            const check = data.checks.find(
              (item) =>
                item.requirement.startsWith('Recorded action: ') &&
                item.citations.some(
                  (citation) =>
                    citation.kind === 'conversation' &&
                    citation.event_kind === 'action' &&
                    citation.turn_id === turn.number,
                ),
            )
            return (
              <button
                key={turn.number}
                className="timeline-event grid-layout"
                aria-pressed={activeTurn?.number === turn.number}
                onClick={() => setActiveNumber(turn.number)}
              >
                <time>{turn.time ?? `Turn ${turn.number}`}</time>
                <span className="timeline-point grid-center">
                  <Icon name="document" size={15} />
                </span>
                <strong className="check-excerpt">
                  {check ? checkTitle(check) : turn.text}
                </strong>
              </button>
            )
          })}
        </div>
        {activeTurn && (
          <div className="timeline-preview flex-center" aria-live="polite">
            <span className="timeline-preview-time">
              {activeTurn.time ?? `Turn ${activeTurn.number}`}
              <small>{activeTurn.speaker}</small>
            </span>
            <div>
              <blockquote>{activeTurn.text}</blockquote>
            </div>
            <EvidenceLink turns={[activeTurn.number]} onOpen={onOpen}>
              View context
            </EvidenceLink>
          </div>
        )}
      </EvidenceSection>
      <Coaching data={data} />
    </>
  )
}
