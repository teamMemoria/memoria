import { createDevCallApi, type DevCallApi } from './devCallApi'
import { reviewRequestStatuses, type ConversationsApi } from '../features/conversations/conversations'
import type { CallApi } from '../types/callReview'
import type { TeamConversation, TeamReviewApi } from '../features/review-queue/teamQueue'

const records = [
  ['C1042', 'Refund request', 'agent-alex-morgan', 'Alex Morgan', '2026-10-08', 'needs-review'],
  ['C1047', 'Gift card balance', 'agent-alex-morgan', 'Alex Morgan', '2026-10-09', 'meets-criteria'],
  ['C1051', 'Lamp exchange', 'agent-priya-shah', 'Priya Shah', '2026-10-12', 'needs-review'],
  ['C1058', 'Card refund timing', 'agent-sam-rivera', 'Sam Rivera', '2026-10-14', 'needs-review'],
  ['C1060', 'Delivery delay', 'agent-priya-shah', 'Priya Shah', '2026-10-10', 'needs-review'],
  ['C1063', 'Address change', 'agent-sam-rivera', 'Sam Rivera', '2026-10-16', 'processing'],
] as const

const conversations: TeamConversation[] = records.map(([id, topic, agentId, agentName, date, automatedResult]) => ({
  id, topic, agentId, agentName, date, automatedResult,
  reviewStatus: automatedResult === 'processing' ? null : 'feedback-ready',
  flag: null,
}))

const team = new Set(conversations.map(({ agentId }) => agentId))

export function createDevConversationsApi(callApi: CallApi): ConversationsApi {
  const [{ flag: _flag, ...conversation }] = conversations
  return {
    async listForAgent(agentId) {
      if (agentId !== conversation.agentId) return []
      const call = await callApi.getCallForAgent(agentId, conversation.id)
      const request = call?.reviewRequest
      return [{ ...conversation, reviewStatus: request ? reviewRequestStatuses[request.status] : conversation.reviewStatus }]
    },
  }
}

export function createDevTeamReviewApi(callApi: DevCallApi = createDevCallApi()): TeamReviewApi {
  function authorize(managerId: string) {
    if (managerId !== 'manager-maya-chen') throw new Error('Team review is available to Managers only.')
  }

  async function teamCall(managerId: string, conversationId: string) {
    authorize(managerId)
    const call = await callApi.getCall(conversationId)
    return call && team.has(call.agentId) ? call : null
  }

  return {
    async listForManager(managerId) {
      authorize(managerId)
      return Promise.all(conversations.map(async (conversation) => {
        const call = await callApi.getCall(conversation.id)
        const request = call?.reviewRequest
        if (!call || !request) return { ...conversation }
        const finding = call.findings.find((item) => item.id === request.findingId)
        return {
          ...conversation,
          reviewStatus: reviewRequestStatuses[request.status],
          flag: { ...request, findingTitle: finding?.title ?? 'Finding unavailable' },
        }
      }))
    },
    async getCallForManager(managerId, conversationId) {
      const call = await teamCall(managerId, conversationId)
      return call ? { call, canDecide: true } : null
    },
    async saveDecision(managerId, conversationId, findingId, decision) {
      const call = await teamCall(managerId, conversationId)
      if (
        !call ||
        call.decision ||
        call.reviewRequest?.findingId !== findingId ||
        call.reviewRequest.status !== 'requested'
      ) {
        throw new Error('This finding cannot be decided.')
      }
      if (!decision.reason.trim() || !decision.feedback.trim()) {
        throw new Error('A reason and feedback are required.')
      }
      // Mirrors the backend: a corrected result is required for corrected, and only then.
      if ((decision.outcome === 'corrected') !== (decision.reviewedResult !== undefined)) {
        throw new Error('A corrected decision needs the corrected result.')
      }
      const saved = {
        outcome: decision.outcome,
        reason: decision.reason.trim(),
        feedback: decision.feedback.trim(),
        managerName: 'Maya Chen',
        decidedAt: new Date().toISOString(),
      }
      await callApi.recordDecision(conversationId, saved)
      return saved
    },
  }
}
