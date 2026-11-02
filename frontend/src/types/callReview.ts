import type { KnowledgeEntry } from './knowledge'

export type AuditResult = 'needs-review' | 'meets-criteria' | 'cannot-assess'
export const auditResults = {
  'needs-review': { label: 'Needs review', tone: 'attention' },
  'meets-criteria': { label: 'Meets criteria', tone: 'positive' },
  'cannot-assess': { label: 'Cannot assess', tone: 'neutral' },
} as const

export type CriterionId =
  | 'procedure'
  | 'answer-support'
  | 'completeness'
  | 'communication-style'

export type TranscriptTurn = {
  number: number
  speaker: 'Agent' | 'Customer'
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
}

export type CallFinding = {
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

export type CallReview = {
  id: string
  agentId: string
  agentName: string
  topic: string
  date: string
  duration: string
  summary: string
  status: 'ready' | 'processing'
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

export interface CallApi {
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
