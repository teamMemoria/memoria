import type {
  ConversationPassage,
  KnowledgeDraft,
  KnowledgeEntry,
  KnowledgeReviewApi,
} from '../types/knowledge'
import { canDecideKnowledge } from '../types/knowledge'
import { refundProcedure } from './devApprovedKnowledge'

const managers: Record<string, { name: string; canDecide: boolean }> = {
  'manager-maya-chen': { name: 'Maya Chen', canDecide: true },
}

function passage(
  conversationId: string,
  turnNumber: number,
  speaker: ConversationPassage['speaker'],
  text: string,
): ConversationPassage {
  return { conversationId, turnNumber, speaker, text }
}

function draft(
  entry: Partial<KnowledgeDraft> & Pick<KnowledgeDraft, 'id' | 'title' | 'topic' | 'status'>,
): KnowledgeDraft {
  return {
    kind: 'knowledge',
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
    updatedAt: '2026-10-20',
    passages: [],
    verificationReference: null,
    decision: null,
    ...entry,
  }
}

const drafts: KnowledgeDraft[] = [
  draft({
    id: 'KD-104',
    title: 'Exchanges for damaged items',
    topic: 'Returns',
    status: 'draft',
    sourceConversationIds: ['C1042', 'C1051', 'C1066'],
    updatedAt: '2026-10-27',
    paragraphs: ['Customers may exchange a damaged item for the same product.'],
    passages: [
      passage('C1051', 6, 'Agent', 'I can swap the damaged lamp for a new one.'),
      passage('C1066', 9, 'Agent', 'We can exchange it for the same item at no cost.'),
    ],
  }),
  draft({
    id: 'KD-103',
    title: 'Refund timing for card payments',
    topic: 'Refunds',
    status: 'draft',
    owner: 'Customer Support Operations',
    sourceConversationIds: ['C1042', 'C1058'],
    updatedAt: '2026-10-25',
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
  draft({
    id: 'KD-102',
    title: 'Missing parcel claims',
    topic: 'Delivery',
    status: 'draft',
    sourceConversationIds: ['C1033'],
    updatedAt: '2026-10-22',
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
  draft({
    id: 'KD-097',
    title: 'Store credit expiry',
    topic: 'Refunds',
    status: 'disputed',
    sourceConversationIds: ['C1019', 'C1024'],
    updatedAt: '2026-10-18',
  }),
  draft({
    id: 'KD-095',
    title: 'Refunds without a receipt',
    topic: 'Refunds',
    status: 'rejected',
    sourceConversationIds: ['C1015'],
    updatedAt: '2026-10-12',
    decision: {
      outcome: 'rejected',
      reason: 'Policy requires proof of purchase.',
      managerName: 'Maya Chen',
      decidedAt: '2026-10-12T14:00:00Z',
    },
  }),
]

export type DevKnowledgeReviewApi = KnowledgeReviewApi & {
  // Lets the development Agent knowledge API read approvals from this session.
  listApproved(): Promise<KnowledgeEntry[]>
}

export function createDevKnowledgeReviewApi(): DevKnowledgeReviewApi {
  // Each API keeps its own copy so decisions survive navigation.
  const saved = structuredClone(drafts)

  function manager(managerId: string) {
    const found = managers[managerId]
    if (!found) throw new Error('Knowledge review is available to Managers only.')
    return found
  }

  function decidable(managerId: string, entryId: string) {
    const { name, canDecide } = manager(managerId)
    if (!canDecide) throw new Error('You do not have knowledge approval permission.')
    const entry = saved.find((item) => item.id === entryId)
    if (!entry || !canDecideKnowledge(entry)) {
      throw new Error('This entry cannot be decided.')
    }
    return { name, entry }
  }

  return {
    async listForManager(managerId) {
      manager(managerId)
      return structuredClone(saved)
    },
    async getForManager(managerId, entryId) {
      const { canDecide } = manager(managerId)
      const entry = saved.find((item) => item.id === entryId)
      return entry ? { entry: structuredClone(entry), canDecide } : null
    },
    async approve(managerId, entryId, verifiedReferenceUrl) {
      const { name, entry } = decidable(managerId, entryId)
      // Matching conversations never stand in for the authoritative reference.
      if (!entry.verificationReference || entry.verificationReference.url !== verifiedReferenceUrl) {
        throw new Error('Approval requires the verification reference.')
      }
      const now = new Date().toISOString()
      Object.assign(entry, {
        status: 'approved',
        approvedAt: now.slice(0, 10),
        approvedBy: name,
        effectiveAt: now.slice(0, 10),
        source: entry.verificationReference,
        updatedAt: now.slice(0, 10),
        decision: { outcome: 'approved', reason: null, managerName: name, decidedAt: now },
      } satisfies Partial<KnowledgeDraft>)
      return structuredClone(entry)
    },
    async reject(managerId, entryId, reason) {
      const { name, entry } = decidable(managerId, entryId)
      if (!reason.trim()) throw new Error('A reason is required.')
      const now = new Date().toISOString()
      Object.assign(entry, {
        status: 'rejected',
        updatedAt: now.slice(0, 10),
        decision: { outcome: 'rejected', reason: reason.trim(), managerName: name, decidedAt: now },
      } satisfies Partial<KnowledgeDraft>)
      return structuredClone(entry)
    },
    async listApproved() {
      return structuredClone(saved.filter((entry) => entry.status === 'approved'))
    },
  }
}
