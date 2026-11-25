import { checkTurns, featuredChecks, linkedCheckTurns, type AssessmentData } from '../assessment-shared/assessment'

export function presentProcedure(data: AssessmentData, activeNumber: number | undefined) {
  const ordered = featuredChecks(data.checks)
  const simulation = data.call.assessmentSource === 'simulation'
  const first = ordered[0]
  const partial = simulation
    ? ordered.find((check) => check.outcome === 'partial' && linkedCheckTurns(data, check).length)
    : undefined
  const featured = !first?.critical && first?.outcome !== 'breach' && partial ? partial : first
  const linked = featured ? linkedCheckTurns(data, featured) : []
  const selected = featured
    ? simulation ? linked.map((turn) => turn.number) : checkTurns(featured)
    : data.turns.map((turn) => turn.number)
  const actions = data.turns.filter((turn) => turn.speaker === 'System action')
  const activeTurn =
    actions.find((turn) => turn.number === activeNumber) ?? actions[0]
  const steps = data.findings.flatMap((finding) => finding.procedureSteps)
  return { featured, linked, selected, actions, activeTurn, steps }
}
