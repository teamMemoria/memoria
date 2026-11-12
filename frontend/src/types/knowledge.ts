export type KnowledgeEntry = {
  id: string
  title: string
  topic: string
  kind: 'procedure' | 'knowledge'
  status: 'approved' | 'draft' | 'disputed' | 'stale' | 'rejected'
  availableToAgentIds: string[]
  version: string
  approvedAt: string | null
  approvedBy: string | null
  effectiveAt: string | null
  lastConfirmedAt: string | null
  owner: string | null
  source: { title: string; url: string | null } | null
  paragraphs: string[]
  steps: { number: number; text: string }[]
}

export interface ApprovedKnowledgeApi {
  listForAgent(agentId: string): Promise<KnowledgeEntry[]>
  getForAgent(agentId: string, entryId: string): Promise<KnowledgeEntry | null>
}

export function canReadKnowledge(entry: KnowledgeEntry, agentId: string) {
  return (
    entry.status === 'approved' && entry.availableToAgentIds.includes(agentId)
  )
}

export type ConversationPassage = {
  conversationId: string
  turnNumber: number
  speaker: 'Agent' | 'Customer'
  text: string
}

export type KnowledgeDecision = {
  outcome: 'approved' | 'rejected'
  reason: string | null
  managerName: string
  decidedAt: string
}

// A knowledge entry as Managers see it in the review queue.
export type KnowledgeDraft = KnowledgeEntry & {
  sourceConversationIds: string[]
  updatedAt: string
  passages: ConversationPassage[]
  // The authoritative source a Manager must check before approving.
  verificationReference: { title: string; url: string } | null
  decision: KnowledgeDecision | null
}

export type KnowledgeReviewDetail = {
  entry: KnowledgeDraft
  // Knowledge permission, supplied by the backend; separate from call review.
  canDecide: boolean
}

export interface KnowledgeReviewApi {
  // Transport capability, separate from the Manager permission returned by the server.
  decisionsAvailable?: boolean
  listForManager(managerId: string): Promise<KnowledgeDraft[]>
  getForManager(
    managerId: string,
    entryId: string,
  ): Promise<KnowledgeReviewDetail | null>
  approve(
    managerId: string,
    entryId: string,
    verifiedReferenceUrl: string,
  ): Promise<KnowledgeDraft>
  reject(
    managerId: string,
    entryId: string,
    reason: string,
  ): Promise<KnowledgeDraft>
}

export function canDecideKnowledge(entry: KnowledgeDraft) {
  return entry.status !== 'approved' && entry.status !== 'rejected'
}
