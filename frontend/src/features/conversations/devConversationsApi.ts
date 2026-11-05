import type { CallApi } from '../../types/callReview'
import type { Conversation, ConversationsApi } from './conversations'
import { getAgentConversations, reviewRequestStatuses } from './conversations'

const conversations: Conversation[] = [
  {
    id: 'C1042',
    topic: 'Refund request',
    agentId: 'agent-alex-morgan',
    agentName: 'Alex Morgan',
    date: '2026-10-08',
    automatedResult: 'needs-review',
    reviewStatus: 'feedback-ready',
  },
]

// Pass the call API to show review requests saved in this session.
export function createDevConversationsApi(callApi?: CallApi): ConversationsApi {
  return {
    async listForAgent(agentId) {
      return Promise.all(
        getAgentConversations(conversations, agentId).map(async (conversation) => {
          const request = (await callApi?.getCallForAgent(agentId, conversation.id))
            ?.reviewRequest
          return {
            ...conversation,
            reviewStatus: request
              ? reviewRequestStatuses[request.status]
              : conversation.reviewStatus,
          }
        }),
      )
    },
  }
}
