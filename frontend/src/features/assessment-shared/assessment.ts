import type {
  AuditCriterion,
  CallFinding,
  CallReview,
  CriterionId,
  ScoringCheck,
  NarrationLoader,
} from '../../types/callReview'
import { canReadKnowledge } from '../../types/knowledge'

export const categories: { id: CriterionId; title: string }[] = [
  { id: 'procedure', title: 'Procedure' },
  { id: 'answer-support', title: 'Answer support' },
  { id: 'completeness', title: 'Completeness' },
  { id: 'communication-style', title: 'Communication style' },
]

// Display only recorded links. No browser-side assessment or inferred check counts.
export function assessmentData(call: CallReview, category: CriterionId) {
  const criterion = call.criteria.find((item) => item.id === category)
  const findings = call.findings.filter((item) => item.criterionId === category)
  const checks = criterion?.scoring?.checks ?? []
  const citedNumbers = [
    ...new Set([
      ...(criterion?.evidenceTurnNumbers ?? []),
      ...checks.flatMap(checkTurns),
      ...(category === 'completeness'
        ? (call.requestLinks ?? []).flatMap((request) => [
            ...request.requestTurns,
            ...request.responseTurns,
          ])
        : []),
      ...findings.flatMap((item) => item.evidenceTurnNumbers),
      ...findings.flatMap((item) =>
        item.procedureSteps.flatMap((step) => step.turnNumbers),
      ),
    ]),
  ]
  const turns =
    call.transcript?.turns.filter((turn) =>
      citedNumbers.includes(turn.number),
    ) ?? []
  const missingTurns = citedNumbers.filter(
    (number) => !turns.some((turn) => turn.number === number),
  )
  const referenceIds = [
    ...new Set(
      [
        criterion?.referenceId,
        ...findings.map((item) => item.referenceId),
      ].filter((id): id is string => Boolean(id)),
    ),
  ]
  // Both roles see only the guidance applicable to the assessed Agent here.
  const references = call.references.filter(
    (entry) =>
      referenceIds.includes(entry.id) && canReadKnowledge(entry, call.agentId),
  )
  return {
    call,
    criterion,
    findings,
    checks,
    turns,
    missingTurns,
    references,
    referenceIds,
  }
}

export type AssessmentData = ReturnType<typeof assessmentData>
export type EvidenceHandler = (
  turns: number[],
  referenceId?: string | null,
  section?: number | null,
  checkId?: string,
) => void
export type ScreenProps = {
  data: AssessmentData
  onOpen: EvidenceHandler
  loadNarration?: NarrationLoader
}
export type EvidenceItem = Pick<
  AuditCriterion | CallFinding,
  'evidenceTurnNumbers' | 'referenceId'
> & { referenceStep?: number | null }

// Presentation ordering only. Scores and outcomes are always supplied by the API.
export function checkTurns(check: ScoringCheck) {
  return [
    ...new Set(
      check.citations.flatMap((citation) =>
        citation.kind === 'conversation' ? [citation.turn_id] : [],
      ),
    ),
  ]
}

export function featuredChecks(checks: ScoringCheck[]) {
  const rank = (check: ScoringCheck) =>
    check.critical
      ? 0
      : check.outcome === 'breach'
        ? 1
        : check.outcome === 'supported'
          ? 2
          : 3
  return [...checks].sort((a, b) => rank(a) - rank(b))
}

export const checkLabels = {
  supported: 'Supported',
  breach: 'Deduction',
  unresolved: 'Unresolved',
  'not-applicable': 'Not applicable',
} as const

// Short card headings; the full recorded requirement remains in check details.
export function checkTitle(check: ScoringCheck) {
  const labels: Record<string, string> = {
    'Give a specific understandable instruction': 'Clear instruction',
    'Express a respectful courtesy': 'Respectful courtesy',
    'Assess wording within supported patterns': 'Wording interpretation',
    'Support the factual assertion and its qualifications': 'Factual support',
  }
  return (
    labels[check.requirement] ??
    check.requirement.replace(/^Recorded action: /, '')
  )
}
