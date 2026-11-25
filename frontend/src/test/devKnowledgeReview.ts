import type {
  ConversationPassage,
  KnowledgeDraft,
  KnowledgeEntry,
  KnowledgeReviewApi,
} from '../types/knowledge'
import { canDecideKnowledge } from '../types/knowledge'
import { refundProcedure } from './devApprovedKnowledge'

const managerName = 'Maya Chen'

function passage(
  conversationId: string,
  turnNumber: number,
  speaker: ConversationPassage['speaker'],
  text: string,
): ConversationPassage {
  return { conversationId, turnNumber, speaker, text }
}

function draft(
  id: string,
  title: string,
  topic: string,
  updatedAt: string,
  entry: Partial<KnowledgeDraft>,
): KnowledgeDraft {
  return {
    id, title, topic, updatedAt,
    kind: 'knowledge',
    status: 'draft',
    availableToAgentIds: ['agent-alex-morgan'],
    version: 'v1',
    approvedAt: null,
    approvedBy: null,
    effectiveAt: null,
    lastConfirmedAt: null,
    owner: null,
    source: null,
    paragraphs: [],
    steps: [],
    sourceConversationIds: [],
    passages: [],
    verificationReference: null,
    decision: null,
    ...entry,
  }
}

const drafts: KnowledgeDraft[] = [
  draft('KD-104', 'Exchanges for damaged items', 'Returns', '2026-10-27', {
    sourceConversationIds: ['C1042', 'C1051', 'C1066'],
    paragraphs: ['Customers may exchange a damaged item for the same product.'],
    passages: [
      passage('C1051', 6, 'Agent', 'I can swap the damaged lamp for a new one.'),
      passage('C1066', 9, 'Agent', 'We can exchange it for the same item at no cost.'),
    ],
  }),
  draft('KD-103', 'Refund timing for card payments', 'Refunds', '2026-10-25', {
    owner: 'Customer Support Operations',
    sourceConversationIds: ['C1042', 'C1058'],
    paragraphs: ['Card refunds usually appear within 5–10 business days.'],
    passages: [
      passage('C1042', 15, 'Agent', 'Your refund has been submitted to the original payment card.'),
      passage('C1058', 11, 'Agent', 'It can take 5 to 10 business days to reach your card.'),
    ],
    verificationReference: {
      title: 'Card refund policy RF-04 v2',
      url: 'https://example.test/policies/RF-04',
    },
  }),
  draft('KD-102', 'Missing parcel claims', 'Delivery', '2026-10-22', {
    sourceConversationIds: ['C1033'],
    paragraphs: ['Open a claim when tracking shows delivered but the parcel is missing.'],
    passages: [
      passage('C1033', 7, 'Agent', 'I’ll open a missing parcel claim for you now.'),
    ],
    verificationReference: {
      title: 'Delivery claims procedure DL-02 v1',
      url: 'https://example.test/policies/DL-02',
    },
  }),
  {
    ...refundProcedure,
    sourceConversationIds: ['C1001', 'C1007', 'C1012', 'C1042'],
    updatedAt: '2026-10-01',
    passages: [],
    verificationReference: null,
    decision: null,
  },
  draft('KD-097', 'Store credit expiry', 'Refunds', '2026-10-18', {
    status: 'disputed',
    sourceConversationIds: ['C1019', 'C1024'],
  }),
  draft('KD-095', 'Refunds without a receipt', 'Refunds', '2026-10-12', {
    status: 'rejected',
    sourceConversationIds: ['C1015'],
    decision: {
      outcome: 'rejected',
      reason: 'Policy requires proof of purchase.',
      managerName,
      decidedAt: '2026-10-12T14:00:00Z',
    },
  }),
]

export type DevKnowledgeReviewApi = KnowledgeReviewApi & {
  listApproved(): Promise<KnowledgeEntry[]>
}

export function createDevKnowledgeReviewApi(): DevKnowledgeReviewApi {
  // Each API keeps its own copy so decisions survive navigation.
  const saved = structuredClone(drafts)

  function manager(managerId: string) {
    if (managerId !== 'manager-maya-chen') throw new Error('Knowledge review is available to Managers only.')
  }

  function find(managerId: string, entryId: string) {
    manager(managerId)
    return saved.find((entry) => entry.id === entryId)
  }

  function decidable(managerId: string, entryId: string) {
    const entry = find(managerId, entryId)
    if (!entry || !canDecideKnowledge(entry)) throw new Error('This entry cannot be decided.')
    return entry
  }

  function update(entry: KnowledgeDraft, fields: Partial<KnowledgeDraft>) {
    Object.assign(entry, { updatedAt: new Date().toISOString().slice(0, 10) }, fields)
    return structuredClone(entry)
  }

  return {
    async listForManager(managerId) {
      manager(managerId)
      return structuredClone(saved)
    },
    async getForManager(managerId, entryId) {
      const entry = find(managerId, entryId)
      return entry ? { entry: structuredClone(entry), canDecide: true } : null
    },
    async approve(managerId, entryId, verifiedReferenceUrl) {
      const entry = decidable(managerId, entryId)
      // Matching conversations never stand in for the authoritative reference.
      if (!entry.verificationReference || entry.verificationReference.url !== verifiedReferenceUrl) {
        throw new Error('Approval requires the verification reference.')
      }
      const now = new Date().toISOString()
      return update(entry, {
        status: 'approved',
        approvedAt: now.slice(0, 10),
        approvedBy: managerName,
        effectiveAt: now.slice(0, 10),
        source: entry.verificationReference,
        decision: { outcome: 'approved', reason: null, managerName, decidedAt: now },
      })
    },
    async reject(managerId, entryId, reason) {
      const entry = decidable(managerId, entryId)
      if (!reason.trim()) throw new Error('A reason is required.')
      const now = new Date().toISOString()
      return update(entry, {
        status: 'rejected',
        decision: { outcome: 'rejected', reason: reason.trim(), managerName, decidedAt: now },
      })
    },
    async unapprove(managerId, entryId, version) {
      const entry = find(managerId, entryId)
      if (entry?.status !== 'approved' || entry.version !== version) {
        throw new Error('This entry cannot be unapproved.')
      }
      const now = new Date().toISOString()
      return update(entry, {
        status: 'draft',
        version: now,
        approvedAt: null,
        approvedBy: null,
        effectiveAt: null,
        source: null,
        updatedAt: now,
        decision: null,
      })
    },
    async listApproved() {
      return structuredClone(saved.filter((entry) => entry.status === 'approved'))
    },
  }
}
