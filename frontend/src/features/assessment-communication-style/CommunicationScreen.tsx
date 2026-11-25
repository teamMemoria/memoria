import { useCommunication } from './controller'
import { Card } from '../../components/ui/card'
import { Icon } from '../../components/Icon'
import {
  Coaching,
  ScoreCard,
  AssessmentSummary,
  MaterialLimits,
  EvidenceLink,
} from '../assessment-shared/AssessmentElements'
import {
  checkTitle,
  checkLabels,
  linkedCheckTurns,
  type ScreenProps,
} from '../assessment-shared/assessment'
import { TranscriptWaveform } from './waveform/TranscriptWaveform'
import './communication-style.css'

export function CommunicationScreen({
  data,
  onOpen,
  loadNarration,
}: ScreenProps) {
  const { checks, phrases, selected, setSelected, evidence, selectTurn } = useCommunication(data)
  const simulation = data.call.assessmentSource === 'simulation'
  const feedback = simulation ? checks.find((check) =>
    (check.outcome === 'partial' || check.outcome === 'breach') &&
    linkedCheckTurns(data, check).some((turn) => turn.speaker === 'Agent'),
  ) : undefined
  return (
    <>
      <section
        className="dashboard-top dashboard-top--three communication-top"
        aria-label="Communication wording checks"
      >
        <ScoreCard data={data} label="Clarity & respect" visual="wording" />
        <Card className="dashboard-card action-area">
          <h2>Agent actions</h2>
          <div className="wording-list">
            {checks.slice(0, 3).map((check, index) => {
              const quote = check.citations.find(
                (citation) => citation.kind === 'conversation',
              )
              return (
                <button
                  className={`wording-check wording-check--${['green', 'blue', 'orange'][index % 3]}`}
                  key={check.id}
                  onClick={() => {
                    if (quote?.kind === 'conversation')
                      selectTurn(quote.turn_id)
                  }}
                >
                  <span>
                    <strong>{checkTitle(check)}</strong>
                    <span className="wording-source">
                      {quote?.kind === 'conversation'
                        ? `Turn ${quote.turn_id}`
                        : 'Source unavailable'}
                    </span>
                  </span>
                  <span className="wording-track" aria-hidden="true">
                    <i
                      style={{
                        width: check.maximum ? `${(100 * (check.earned ?? 0)) / check.maximum}%` : '0%',
                      }}
                    />
                  </span>
                  <span className="wording-caption">
                    <span className={`card-badge${check.outcome === 'supported' ? '' : ' card-badge--attention'}`}>
                      {checkLabels[check.outcome]}
                    </span>
                    {quote && <q>{quote.quote}</q>}
                  </span>
                </button>
              )
            })}
          </div>
          {!checks.length &&
            (data.criterion?.scoring ? (
              <p className="card-subtitle">
                No assessed Agent wording supplied.
              </p>
            ) : (
              <AssessmentSummary data={data} onOpen={onOpen} />
            ))}
        </Card>
        <Card className="dashboard-card phrase-card">
          <div className="card-eyebrow">
            Phrases
            <Icon name="conversations" size={19} />
          </div>
          <div className="phrase-cloud">
            {phrases.slice(0, 4).map((citation, index) => (
              <button
                className={`phrase phrase--${['green', 'blue', 'peach', 'blue'][index]}`}
                key={`${citation.turn_id}-${index}`}
                aria-label={`Select turn ${citation.turn_id}: ${citation.quote}`}
                onClick={() => selectTurn(citation.turn_id)}
              >
                <q>
                  {citation.quote.match(/^(?:\S+\s+){0,5}\S+/)?.[0] ??
                    citation.quote}
                </q>
                {citation.quote.trim().split(/\s+/).length > 6 && (
                  <span aria-hidden="true">…</span>
                )}
              </button>
            ))}
          </div>
          {!phrases.length && (
            <p className="card-subtitle">No assessed phrases available.</p>
          )}
        </Card>
      </section>
      <section ref={evidence} className="evidence-section evidence-section--plain" aria-labelledby="communication-evidence-title">
        <TranscriptWaveform
          key={`${data.call.id}-${data.call.assessmentVersion?.transcript ?? ''}`}
          agentName={data.call.agentName}
          loadNarration={loadNarration}
          voiceOnByDefault={simulation}
          turns={data.call.transcript?.turns ?? []}
          selected={selected}
          onSelect={setSelected}
          onOpen={onOpen}
        />
        <MaterialLimits data={data} />
      </section>
      {feedback && (
        <section className="coaching" aria-label="Wording feedback">
          <div className="coaching-summary">
            <span className="coaching-icon"><Icon name="info" size={23} /></span>
            <div>
              <h2>{checkTitle(feedback)}</h2>
              <p>{feedback.explanation}</p>
              <EvidenceLink
                turns={linkedCheckTurns(data, feedback).map((turn) => turn.number)}
                checkId={feedback.id}
                onOpen={onOpen}
              >
                View wording evidence
              </EvidenceLink>
            </div>
          </div>
        </section>
      )}
      <Coaching data={data} />
    </>
  )
}
