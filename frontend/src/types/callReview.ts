import type { KnowledgeEntry } from './knowledge.js'

export type AuditResult = 'needs-review' | 'meets-criteria' | 'cannot-assess'
export const auditResults = {
  'needs-review': { label: 'Needs review', tone: 'attention' },
  'meets-criteria': { label: 'Meets criteria', tone: 'positive' },
  'cannot-assess': { label: 'Cannot assess', tone: 'neutral' },
} as const

export type CriterionId =
  'procedure' | 'answer-support' | 'completeness' | 'communication-style'

export type TranscriptTurn = {
  number: number
  speaker: 'Agent' | 'Customer' | 'System action'
  text: string
  time: string | null
}

export type AuditCriterion = {
  id: CriterionId
  title: string
  result: AuditResult
  explanation: string
  evidenceTurnNumbers: number[]
  findingId: string | null
  referenceId: string | null
  scoring?: AssessmentScoring | null
}

export type CallFinding = {
  critical?: boolean
  id: string
  title: string
  criterionId: CriterionId
  explanation: string
  suggestion: string
  evidenceTurnNumbers: number[]
  referenceId: string | null
  referenceStep: number | null
  procedureSteps: {
    label: string
    status: 'observed' | 'not-visible' | 'cannot-assess'
    turnNumbers: number[]
    note: string | null
  }[]
}

export function pilotLabel(call: CallReview) {
  const rules = call.assessmentVersion?.rules ?? ''
  const review = rules.includes('+luna:') ? ' Luna reviewed the transcript checks.' : ''
  if (rules.startsWith('luna-transcript-pilot-')) return 'Luna pilot (transcript checks only)'
  if (rules.startsWith('subscription-refusal-pilot-')) return 'Subscription pilot (extension refusal only)'
  if (rules.startsWith('subscription-gold-pilot-')) return 'Subscription pilot (Gold extension request only)'
  if (rules.startsWith('observed-pilot-')) return 'Conversation pilot (recorded evidence).' + review
  if (rules.startsWith('product-faq-pilot-')) return 'Product care pilot (procedure score covers FAQ search only).' + review
  if (rules.startsWith('pricing-pilot-')) return 'Pricing pilot (draft scoring criteria)'
  return null
}

export type CallReview = {
  assessmentSource?: 'simulation'
  sourceId?: string | null
  id: string
  agentId: string
  agentName: string
  topic: string
  date: string | null
  duration: string | null
  summary: string
  status: 'ready' | 'partial' | 'processing' | 'unavailable'
  overallScoring?: OverallScoring | null
  assessmentVersion?: {
    sourceId?: string
    asOf: string
    rules: string
    scoringMethod?: string | null
    transcript: string
  } | null
  requestLinks?: RequestLink[]
  criteria: AuditCriterion[]
  findings: CallFinding[]
  transcript: {
    complete: boolean
    turns: TranscriptTurn[]
    unavailableReason: string | null
  } | null
  references: KnowledgeEntry[]
  agentContext: AgentContext | null
  reviewRequest: ReviewRequest | null
  decision: {
    outcome: 'confirmed' | 'corrected' | 'dismissed' | 'cannot-assess'
    reason: string
    feedback: string
    managerName: string
    decidedAt: string
  } | null
}

export const decisionOutcomes = {
  confirmed: {
    label: 'Confirmed',
    description: 'The automatic feedback is correct.',
  },
  corrected: {
    label: 'Corrected',
    description: 'The feedback needs a correction, explained below.',
  },
  dismissed: {
    label: 'Dismissed',
    description: 'The feedback does not apply to this call.',
  },
  'cannot-assess': {
    label: 'Cannot assess',
    description: 'The evidence is not enough to decide.',
  },
} as const satisfies Record<NonNullable<CallReview['decision']>['outcome'], { label: string; description: string }>

export type AgentContext = {
  text: string
  savedAt: string
}

export type ReviewRequest = {
  findingId: string
  reason: string
  requestedAt: string
  status: 'requested' | 'complete'
}

export type NarrationLoader = (
  turn: TranscriptTurn,
  voice: string,
  signal: AbortSignal,
) => Promise<Blob>

export interface NarrationApi {
  getNarration?(
    userId: string,
    conversationId: string,
    turn: TranscriptTurn,
    voice: string,
    signal: AbortSignal,
  ): Promise<Blob>
}

export interface CallApi extends NarrationApi {
  getCallForAgent(
    agentId: string,
    conversationId: string,
  ): Promise<CallReview | null>
  // Saving context never requests a Manager review; flagging is separate.
  saveContext(
    agentId: string,
    conversationId: string,
    text: string,
  ): Promise<AgentContext>
  requestReview(
    agentId: string,
    conversationId: string,
    findingId: string,
    reason: string,
  ): Promise<ReviewRequest>
}

export type FindingReviewDetail = {
  call: CallReview
  canDecide: boolean
}

export interface ManagerCallApi extends NarrationApi {
  startAnalysis?(managerId: string, conversationId: string): Promise<unknown>
  getCallForManager(
    managerId: string,
    conversationId: string,
  ): Promise<FindingReviewDetail | null>
}

export type CanonicalCitation =
  | {
      kind: 'conversation'
      conversation_id: string
      transcript_version: string
      turn_id: number
      event_kind: 'message' | 'action'
      quote: string
    }
  | {
      kind: 'reference'
      origin?: string
      reference_id: string
      reference_version: string
      section_id: string
      quote: string
    }

export type ScoringCheck = {
  id: string
  ruleId: string
  requirement: string
  outcome: 'supported' | 'partial' | 'breach' | 'unresolved' | 'not-applicable'
  earned: number | null
  maximum: number
  explanation: string
  advice: string
  citations: CanonicalCitation[]
  critical: boolean
}

export type AssessmentScoring = {
  score: number | null
  coverage: number | null
  earned: number
  assessable: number
  possible: number | null
  checks: ScoringCheck[]
  limitations: string[]
  interpretationLimits: string[]
  processingError: string | null
}

export type OverallScoring = {
  score: number | null
  coverage: number | null
  profileId: string | null
  profileVersion: string | null
  reason: string | null
  weights: Record<CriterionId, number> | null
}

export function percentage(
  value: number | null | undefined,
  unavailable = 'Not scored',
) {
  return value == null ? unavailable : `${Math.round(value)}%`
}

export function hasMidpointScoring(method: string | null | undefined) {
  return method === 'calibrated-simulation-midpoint-v1' ||
    (method?.startsWith('applicable-points-midpoint-') ?? false)
}

export function assessmentPercentage(scoring: {
  score: number | null
  coverage: number | null
}) {
  return scoring.coverage === 0
    ? 'Cannot assess'
    : percentage(scoring.score, 'Cannot assess')
}

export type RequestLink = {
  id: string
  text: string
  state: string
  requestTurns: number[]
  responseTurns: number[]
  limitations: string[]
}
