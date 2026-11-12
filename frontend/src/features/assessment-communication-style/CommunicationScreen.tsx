import { useRef, useState } from 'react'
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
  checkTurns,
  featuredChecks,
  type ScreenProps,
} from '../assessment-shared/assessment'
import { TranscriptWaveform } from './waveform/TranscriptWaveform'
import './communication-style.css'

export function CommunicationScreen({
  data,
  onOpen,
  loadNarration,
}: ScreenProps) {
  const checks = featuredChecks(data.checks).filter(
    (check) => check.outcome === 'supported' || check.outcome === 'breach',
  )
  const [selected, setSelected] = useState(
    checks.flatMap(checkTurns)[0] ?? data.turns[0]?.number,
  )
  const evidence = useRef<HTMLDivElement>(null)
  function selectTurn(turn: number) {
    setSelected(turn)
    const target = evidence.current?.querySelector<HTMLButtonElement>(
      `[data-turn="${turn}"]`,
    )
    target?.focus({ preventScroll: true })
    target?.scrollIntoView({
      block: 'center',
      inline: 'center',
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'instant'
        : 'smooth',
    })
  }
  const phrases = checks
    .flatMap((check) =>
      check.citations.flatMap((citation) =>
        citation.kind === 'conversation' &&
        data.turns.some(
          (turn) =>
            turn.number === citation.turn_id && turn.speaker === 'Agent',
        )
          ? [citation]
          : [],
      ),
    )
    .filter(
      (citation, index, all) =>
        all.findIndex(
          (other) =>
            other.turn_id === citation.turn_id &&
            other.quote === citation.quote,
        ) === index,
    )
  const selectedCheck = checks.find((check) =>
    checkTurns(check).includes(selected ?? -1),
  )
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
                      <Icon name="arrowRight" size={14} />
                    </span>
                  </span>
                  <span className="wording-track" aria-hidden="true">
                    <i
                      style={{
                        width: check.outcome === 'supported' ? '100%' : '0%',
                      }}
                    />
                  </span>
                  <span className="wording-caption">
                    <small>{checkLabels[check.outcome]} · </small>
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
      <Card ref={evidence} className="dashboard-card evidence-section">
        <TranscriptWaveform
          key={`${data.call.id}-${data.call.assessmentVersion?.transcript ?? ''}`}
          agentName={data.call.agentName}
          loadNarration={loadNarration}
          turns={data.call.transcript?.turns ?? []}
          selected={selected}
          onSelect={setSelected}
          onOpen={onOpen}
        />
        {selectedCheck && (
          <EvidenceLink
            turns={checkTurns(selectedCheck)}
            checkId={selectedCheck.id}
            onOpen={onOpen}
          >
            View check and reference
          </EvidenceLink>
        )}
        <MaterialLimits data={data} />
      </Card>
      <Coaching data={data} />
    </>
  )
}
