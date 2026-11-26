import { Icon } from '../../components/Icon'
import type { CanonicalCitation, ScoringCheck, TranscriptTurn } from '../../types/callReview'
import { checkLabels, matchesRecordedTurn } from './assessment'
import './check-evidence-summary.css'

type ConversationCitation = Extract<CanonicalCitation, { kind: 'conversation' }>

const formatPoints = new Intl.NumberFormat('en', {
  maximumFractionDigits: 2,
  useGrouping: false,
}).format

function customerFollowUps(
  check: ScoringCheck,
  checks: ScoringCheck[],
  turns: ReadonlyMap<number, TranscriptTurn>,
  passages: ConversationCitation[],
) {
  const lastCitedTurn = passages.at(-1)?.turn_id
  if (lastCitedTurn === undefined) return []
  const followUps = new Map<number, ConversationCitation>()
  for (const related of checks) {
    if (related.id === check.id || related.ruleId !== 'answer-support.recorded_outcomes') continue
    // A recorded outcome check must cite the same passage to supply related context.
    const citations = related.citations.filter((citation) => citation.kind === 'conversation')
    const sharedSources = citations.filter((citation) => passages.some((passage) =>
      sameRecording(citation, passage) && citation.turn_id === passage.turn_id && citation.quote === passage.quote,
    ))
    if (!sharedSources.length) continue
    for (const citation of citations) {
      const turn = turns.get(citation.turn_id)
      if (turn?.speaker === 'Customer' && turn.number > lastCitedTurn &&
        matchesRecordedTurn(citation, turn) && sharedSources.some((shared) => sameRecording(citation, shared))) {
        followUps.set(citation.turn_id, citation)
      }
    }
  }
  return [...followUps.values()].sort((a, b) => a.turn_id - b.turn_id)
}

function sameRecording(a: ConversationCitation, b: ConversationCitation) {
  return a.conversation_id === b.conversation_id && a.transcript_version === b.transcript_version
}

function CitedTurn({ citation, onOpen }: {
  citation: ConversationCitation
  onOpen: (number: number) => void
}) {
  return (
    <button type="button" className="check-cited-turn" onClick={() => onOpen(citation.turn_id)}>
      <strong>Turn {citation.turn_id}</strong>
      <span>{citation.quote}</span>
      <Icon name="arrowRight" size={15} />
    </button>
  )
}

export function CheckEvidenceSummary({ check, checks, turns, title, onOpen }: {
  check: ScoringCheck
  checks: ScoringCheck[]
  turns: TranscriptTurn[]
  title: string
  onOpen: (number: number) => void
}) {
  const recordedTurns = new Map(turns.map((turn) => [turn.number, turn]))
  const conversation: ConversationCitation[] = []
  const unavailable: ConversationCitation[] = []
  for (const citation of check.citations) {
    if (citation.kind !== 'conversation') continue
    const turn = recordedTurns.get(citation.turn_id)
    const passages = turn && matchesRecordedTurn(citation, turn) ? conversation : unavailable
    passages.push(citation)
  }
  conversation.sort((a, b) => a.turn_id - b.turn_id)
  const references = check.citations.filter((citation) => citation.kind === 'reference')
  const assumptions = references.filter((citation) => citation.origin === 'synthetic assumptions')
  const guidance = references.filter((citation) => citation.origin !== 'synthetic assumptions')
  const followUps = customerFollowUps(check, checks, recordedTurns, conversation)
  const points = check.earned == null ? 'Unscored' : `${formatPoints(check.earned)}/${formatPoints(check.maximum)} points`
  return (
    <div className="check-evidence-summary">
      <div className="check-result" data-outcome={check.outcome}>
        <div className="check-result-meta flex-center">
          <strong>{checkLabels[check.outcome]}{check.critical && ' · Critical check'}</strong>
          <strong>{points}</strong>
        </div>
        {check.explanation && <p>{check.explanation}</p>}
        {check.advice && <p>{check.advice}</p>}
      </div>
      {conversation.length > 0 && (
        <section>
          <h3>Conversation evidence</h3>
          <div className="check-cited-turns">
            {conversation.map((citation, index) => (
              <CitedTurn key={index} citation={citation} onOpen={onOpen} />
            ))}
          </div>
        </section>
      )}
      {unavailable.length > 0 && <p className="source-note">Some cited passages are unavailable in the recorded transcript.</p>}
      {guidance.length > 0 && (
        <section>
          <h3>{guidance.every((citation) => citation.origin === 'ABCD publisher guidance') ? 'Publisher guidance' : 'Reference guidance'}</h3>
          {guidance.map((citation, index) => (
            <figure className="check-guidance-quote" key={index}>
              <blockquote>{citation.quote}</blockquote>
              <figcaption>
                {citation.origin === 'ABCD publisher guidance' ? 'ABCD publisher guidance' : 'Guideline/rubric section'}
                {' · '}Reference {citation.reference_id}
              </figcaption>
            </figure>
          ))}
        </section>
      )}
      {followUps.length > 0 && (
        <section className="check-follow-up">
          <h3>Customer follow-up</h3>
          {followUps.map((citation) => <CitedTurn key={citation.turn_id} citation={citation} onOpen={onOpen} />)}
        </section>
      )}
      {!check.citations.length && <p className="source-note">No linked evidence supplied.</p>}
      {(title !== check.requirement || references.length > 0 || unavailable.length > 0) && (
        <details className="check-source-details">
          <summary>{assumptions.length ? 'Demo assumptions and source details' : 'Source details'}</summary>
          {title !== check.requirement && <p>{check.requirement}</p>}
          {unavailable.map((citation, index) => (
            <blockquote key={index}>
              <strong>Unmatched citation · Turn {citation.turn_id}</strong>
              <p>{citation.quote}</p>
            </blockquote>
          ))}
          {assumptions.map((citation, index) => <blockquote key={index}>{citation.quote}</blockquote>)}
          {guidance.length > 0 && (
            <details className="source-provenance">
              <summary>Reference version and eligibility</summary>
              {guidance.map((citation, index) => (
                <div key={index}>
                  <small>Reference {citation.reference_id} · {citation.section_id}</small>
                  <small>Version {citation.reference_version}</small>
                  {!citation.origin && <small>Eligible at the recorded assessment date</small>}
                </div>
              ))}
            </details>
          )}
        </details>
      )}
    </div>
  )
}
