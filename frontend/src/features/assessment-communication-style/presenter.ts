import { featuredChecks, type AssessmentData } from '../assessment-shared/assessment'

export function presentCommunication(data: AssessmentData) {
  const checks = featuredChecks(data.checks).filter(
    (check) => ['supported', 'partial', 'breach'].includes(check.outcome),
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
  return { checks, phrases }
}
