import type { AssessmentData } from '../assessment-shared/assessment'

export function presentCompleteness(data: AssessmentData, selection: string | undefined) {
  const requests = data.call.requestLinks ?? []
  const promises = requests.filter((request) => request.state === 'promised')
  const unresolved = data.checks.filter(
    (check) => check.outcome === 'unresolved',
  )
  const answered = requests.filter(
    (request) => request.state === 'answered' && request.responseTurns.length,
  )
  const selected =
    requests.find((request) => request.id === selection) ?? requests[0]
  const previewTurns = data.turns.filter(
    (turn) =>
      selected &&
      [...selected.requestTurns, ...selected.responseTurns].includes(
        turn.number,
      ),
  )
  return { requests, promises, unresolved, answered, selected, previewTurns }
}
