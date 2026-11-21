import { checkTurns, featuredChecks, type AssessmentData } from '../assessment-shared/assessment'

export function presentCommunication(data: AssessmentData, selected: number | undefined) {
  const checks = featuredChecks(data.checks).filter(
    (check) => check.outcome === 'supported' || check.outcome === 'breach',
  )
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
  return { checks, phrases, selectedCheck }
}
