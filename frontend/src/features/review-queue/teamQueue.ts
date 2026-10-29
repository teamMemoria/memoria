import type { ReviewRequest } from '../../types/callReview'
import {
  conversationStatusLabels,
  filterConversations,
  type Conversation,
  type ConversationStatusFilter,
} from '../conversations/conversations'

export type FlaggedFeedback = ReviewRequest & { findingTitle: string }

// A team conversation as Managers see it, with the agent's flag if any.
export type TeamConversation = Conversation & { flag: FlaggedFeedback | null }

export interface TeamReviewApi {
  listForManager(managerId: string): Promise<TeamConversation[]>
}

// Managers land on flagged feedback first.
export const defaultQueueStatus = 'review-requested'

export function queueStatusFrom(value: string | null): ConversationStatusFilter {
  return value !== null && value in conversationStatusLabels
    ? (value as ConversationStatusFilter)
    : defaultQueueStatus
}

export function filterTeamConversations(
  conversations: TeamConversation[],
  { query, status }: { query: string; status: ConversationStatusFilter },
) {
  const search = query.trim().toLowerCase()
  const byStatus = filterConversations(conversations, { query: '', status })
  return (byStatus as TeamConversation[])
    .filter((conversation) =>
      [
        conversation.id,
        conversation.topic,
        conversation.agentName,
        conversation.flag?.reason,
        conversation.flag?.findingTitle,
      ]
        .join(' ')
        .toLowerCase()
        .includes(search),
    )
    .sort((first, second) =>
      (second.flag?.requestedAt ?? second.date).localeCompare(
        first.flag?.requestedAt ?? first.date,
      ),
    )
}

export function findingReviewPath(conversation: TeamConversation, search = '') {
  return conversation.flag
    ? `/manager/conversations/${encodeURIComponent(conversation.id)}/findings/${encodeURIComponent(conversation.flag.findingId)}${search}`
    : null
}
