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
