import type { DevCallApi } from '../../lib/devCallApi'
import { reviewRequestStatuses } from '../conversations/conversations'
import type { TeamConversation, TeamReviewApi } from './teamQueue'

const managers: Record<string, { name: string; team: string[]; canDecide: boolean }> = {
  'manager-maya-chen': {
    name: 'Maya Chen',
    team: ['agent-alex-morgan', 'agent-priya-shah', 'agent-sam-rivera'],
    canDecide: true,
  },
}

const conversations: TeamConversation[] = [
  {
    id: 'C1042',
    topic: 'Refund request',
    agentId: 'agent-alex-morgan',
    agentName: 'Alex Morgan',
    date: '2026-10-08',
    automatedResult: 'needs-review',
    reviewStatus: 'feedback-ready',
    flag: null,
  },
  {
    id: 'C1047',
    topic: 'Gift card balance',
    agentId: 'agent-alex-morgan',
    agentName: 'Alex Morgan',
    date: '2026-10-09',
    automatedResult: 'meets-criteria',
    reviewStatus: 'feedback-ready',
    flag: null,
  },
  {
    id: 'C1051',
    topic: 'Lamp exchange',
    agentId: 'agent-priya-shah',
    agentName: 'Priya Shah',
    date: '2026-10-12',
    automatedResult: 'needs-review',
    reviewStatus: 'review-requested',
    flag: {
      findingId: 'answer-support',
      findingTitle: 'Exchange offered without checking stock.',
      reason: 'Stock was checked in the order system before the call.',
      requestedAt: '2026-10-13T09:30:00Z',
      status: 'requested',
    },
  },
  {
    id: 'C1058',
    topic: 'Card refund timing',
    agentId: 'agent-sam-rivera',
    agentName: 'Sam Rivera',
    date: '2026-10-14',
    automatedResult: 'needs-review',
    reviewStatus: 'review-requested',
    flag: {
      findingId: 'completeness',
      findingTitle: 'Refund timeline not confirmed with the customer.',
      reason: 'The customer confirmed the timeline after the transcript cut off.',
      requestedAt: '2026-10-15T16:10:00Z',
      status: 'requested',
    },
  },
  {
    id: 'C1060',
    topic: 'Delivery delay',
    agentId: 'agent-priya-shah',
    agentName: 'Priya Shah',
    date: '2026-10-10',
    automatedResult: 'needs-review',
    reviewStatus: 'review-complete',
    flag: {
      findingId: 'procedure-order',
      findingTitle: 'Tracking checked after offering compensation.',
      reason: 'Tracking was checked on a second screen first.',
      requestedAt: '2026-10-11T11:00:00Z',
      status: 'complete',
    },
  },
  {
    id: 'C1063',
    topic: 'Address change',
    agentId: 'agent-sam-rivera',
    agentName: 'Sam Rivera',
    date: '2026-10-16',
    automatedResult: 'processing',
    reviewStatus: null,
    flag: null,
  },
]

// Pass the call API to read flags and save decisions made in this session.
export function createDevTeamReviewApi(callApi?: DevCallApi): TeamReviewApi {
  function manager(managerId: string) {
    const found = managers[managerId]
    if (!found) throw new Error('Team review is available to Managers only.')
    return found
  }

  async function teamCall(managerId: string, conversationId: string) {
    const { team } = manager(managerId)
    const call = await callApi?.getCall(conversationId)
    return call && team.includes(call.agentId) ? call : null
  }

  return {
    async listForManager(managerId) {
      const { team } = manager(managerId)
      return Promise.all(
        conversations
          .filter((conversation) => team.includes(conversation.agentId))
          .map(async (conversation) => {
            const call = await callApi?.getCall(conversation.id)
            const request = call?.reviewRequest
            if (!call || !request) return structuredClone(conversation)
            return {
              ...structuredClone(conversation),
              reviewStatus: reviewRequestStatuses[request.status],
              flag: {
                ...request,
                findingTitle:
                  call.findings.find((finding) => finding.id === request.findingId)?.title ??
                  'Finding unavailable',
              },
            }
          }),
      )
    },
    async getCallForManager(managerId, conversationId) {
      const call = await teamCall(managerId, conversationId)
      return call ? { call, canDecide: manager(managerId).canDecide } : null
    },
    async saveDecision(managerId, conversationId, findingId, decision) {
      const { name, canDecide } = manager(managerId)
      if (!canDecide) throw new Error('You do not have call review permission.')
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
        managerName: name,
        decidedAt: new Date().toISOString(),
      }
      await callApi!.recordDecision(conversationId, saved)
      return saved
    },
  }
}
