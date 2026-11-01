import type { KnowledgeDraft, KnowledgeReviewApi } from '../types/knowledge'
import { refundProcedure } from './devApprovedKnowledge'

const managerIds = ['manager-maya-chen']

function draft(
  entry: Partial<KnowledgeDraft> & Pick<KnowledgeDraft, 'id' | 'title' | 'topic' | 'status'>,
): KnowledgeDraft {
  return {
    kind: 'knowledge',
    availableToAgentIds: [],
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
  }),
  draft({
    id: 'KD-103',
    title: 'Refund timing for card payments',
    topic: 'Refunds',
    status: 'draft',
    sourceConversationIds: ['C1042', 'C1058'],
    updatedAt: '2026-10-25',
    paragraphs: ['Card refunds usually appear within 5–10 business days.'],
  }),
  draft({
    id: 'KD-102',
    title: 'Missing parcel claims',
    topic: 'Delivery',
    status: 'draft',
    sourceConversationIds: ['C1033'],
    updatedAt: '2026-10-22',
  }),
  {
    ...refundProcedure,
    sourceConversationIds: ['C1001', 'C1007', 'C1012', 'C1042'],
    updatedAt: '2026-10-01',
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
  }),
]

export function createDevKnowledgeReviewApi(): KnowledgeReviewApi {
  // Each API keeps its own copy so later decisions survive navigation.
  const saved = structuredClone(drafts)

  return {
    async listForManager(managerId) {
      if (!managerIds.includes(managerId)) {
        throw new Error('Knowledge review is available to Managers only.')
      }
      return structuredClone(saved)
    },
  }
}
