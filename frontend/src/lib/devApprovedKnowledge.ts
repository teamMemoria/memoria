import type { ApprovedKnowledgeApi, KnowledgeEntry } from '../types/knowledge'
import { canReadKnowledge } from '../types/knowledge'
import type { DevKnowledgeReviewApi } from './devKnowledgeReview'

export const refundProcedure: KnowledgeEntry = {
  id: 'RP-01',
  title: 'Refund handling',
  topic: 'Refunds',
  kind: 'procedure',
  status: 'approved',
  availableToAgentIds: ['agent-alex-morgan'],
  version: 'v1',
  approvedAt: '2026-10-01',
  approvedBy: null,
  effectiveAt: '2026-10-01',
  lastConfirmedAt: null,
  owner: 'Customer Support Operations',
  source: { title: 'Refund handling procedure RP-01 v1', url: null },
  paragraphs: ['Applies to damaged-item refund requests, including C1042.'],
  steps: [
    { number: 1, text: 'Identify the customer.' },
    {
      number: 2,
      text: 'Verify the order, customer match and refund eligibility before offering a refund.',
    },
    {
      number: 3,
      text: 'For an eligible purchase paid by card, explain that the refund may return to the original payment card. Obtain the customer’s agreement.',
    },
    {
      number: 4,
      text: 'Submit the refund and confirm the method and next step.',
    },
  ],
}

// Pass the review API to include entries approved in this session.
export function createDevApprovedKnowledgeApi(
  review?: Pick<DevKnowledgeReviewApi, 'listApproved'>,
): ApprovedKnowledgeApi {
  async function readable(agentId: string) {
    const entries = review
      ? await review.listApproved()
      : [structuredClone(refundProcedure)]
    return entries.filter((entry) => canReadKnowledge(entry, agentId))
  }

  return {
    async listForAgent(agentId) {
      return readable(agentId)
    },
    async getForAgent(agentId, entryId) {
      return (await readable(agentId)).find((entry) => entry.id === entryId) ?? null
    },
  }
}
