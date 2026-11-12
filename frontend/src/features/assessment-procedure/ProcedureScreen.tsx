import { useState } from 'react'
import { ConversationChart } from '../assessment-shared/ConversationChart'
import { Icon } from '../../components/Icon'
import { Card } from '../../components/ui/card'
import {
  Coaching,
  ScoreCard,
  Quote,
  EvidenceLink,
  AssessmentSummary,
  CheckList,
  EvidenceNotes,
  MaterialLimits,
} from '../assessment-shared/AssessmentElements'
import {
  checkTurns,
  checkTitle,
  featuredChecks,
  type ScreenProps,
} from '../assessment-shared/assessment'
import './procedure.css'

export function ProcedureScreen({ data, onOpen }: ScreenProps) {
  const featured = featuredChecks(data.checks)[0]
  const selected = featured
    ? checkTurns(featured)
    : data.turns.map((turn) => turn.number)
  const actions = data.turns.filter((turn) => turn.speaker === 'System action')
  const [activeNumber, setActiveNumber] = useState(actions[0]?.number)
  const activeTurn =
    actions.find((turn) => turn.number === activeNumber) ?? actions[0]
  const steps = data.findings.flatMap((finding) => finding.procedureSteps)
  return (
    <>
      <section
        className="dashboard-top dashboard-top--three"
        aria-label="Procedure checks"
      >
        <ScoreCard data={data} label="Procedure checks" visual="half" />
        <Card className="dashboard-card finding-card">
          <div className="card-eyebrow">
            {featured?.outcome === 'breach' ? 'Finding' : 'Assessment'}
          </div>
          {featured ? (
            <>
              <h2>{featured.requirement.replace(/^Recorded action: /, '')}</h2>
              <p className="card-subtitle check-excerpt">
                {featured.explanation}
              </p>
            </>
          ) : (
            <AssessmentSummary data={data} onOpen={onOpen} />
          )}
          {selected.length > 0 && (
            <div className="compact-evidence">
              {data.turns
                .filter((turn) => selected.includes(turn.number))
                .slice(0, 2)
                .map((turn) => (
                  <Quote key={turn.number} turn={turn} onOpen={onOpen} />
                ))}
            </div>
          )}
          {featured && (
            <EvidenceLink
              turns={selected}
              checkId={featured.id}
              onOpen={onOpen}
            >
              Compare evidence
            </EvidenceLink>
          )}
        </Card>
        <Card className="dashboard-card action-area">
          <h2>Agent actions</h2>
          {data.criterion?.scoring ? (
            <CheckList checks={data.checks} onOpen={onOpen} />
          ) : (
            <div className="procedure-checks">
              {steps.map((step, index) => (
                <div className="check-row" key={index}>
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
          {featured?.citations.some(
            (citation) => citation.kind === 'reference',
          ) && (
            <EvidenceLink turns={[]} checkId={featured.id} onOpen={onOpen}>
              Procedure reference
            </EvidenceLink>
          )}
          {data.referenceIds.map((id) => (
            <EvidenceLink key={id} turns={[]} referenceId={id} onOpen={onOpen}>
              Reference {id}
            </EvidenceLink>
          ))}
        </Card>
      </section>
      <Card className="dashboard-card evidence-section">
        <div className="section-heading">
          <h2>Evidence</h2>
          <span className="chart-legend">Recorded turn / action order</span>
        </div>
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
                className="timeline-event"
                aria-pressed={activeTurn?.number === turn.number}
                onClick={() => setActiveNumber(turn.number)}
              >
                <time>{turn.time ?? `Turn ${turn.number}`}</time>
                <span className="timeline-point">
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
          <div className="timeline-preview" aria-live="polite">
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
        <EvidenceNotes data={data} />
        <MaterialLimits data={data} />
      </Card>
      <Coaching data={data} />
    </>
  )
}
