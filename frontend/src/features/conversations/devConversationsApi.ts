import type { Conversation, ConversationsApi } from './conversations'
import { getAgentConversations } from './conversations'

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

export function createDevConversationsApi(): ConversationsApi {
  return {
    async listForAgent(agentId) {
      return getAgentConversations(conversations, agentId).map((conversation) => ({
        ...conversation,
      }))
    },
  }
}
