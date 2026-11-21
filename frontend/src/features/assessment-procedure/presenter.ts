import { checkTurns, featuredChecks, type AssessmentData } from '../assessment-shared/assessment'

export function presentProcedure(data: AssessmentData, activeNumber: number | undefined) {
  const featured = featuredChecks(data.checks)[0]
  const selected = featured
    ? checkTurns(featured)
    : data.turns.map((turn) => turn.number)
  const actions = data.turns.filter((turn) => turn.speaker === 'System action')
  const activeTurn =
    actions.find((turn) => turn.number === activeNumber) ?? actions[0]
  const steps = data.findings.flatMap((finding) => finding.procedureSteps)
  return { featured, selected, actions, activeTurn, steps }
}
