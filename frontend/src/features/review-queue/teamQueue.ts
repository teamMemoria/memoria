import type { AuditResult, CallReview, ReviewRequest, ManagerCallApi } from '../../types/callReview'
import {
  conversationStatusLabels,
  filterConversations,
  type Conversation,
  type ConversationStatusFilter,
} from '../conversations/conversations'

export type FlaggedFeedback = ReviewRequest & { findingTitle: string }

// A team conversation as Managers see it, with the agent's flag if any.
export type TeamConversation = Conversation & { flag: FlaggedFeedback | null }

export type ManagerDecision = NonNullable<CallReview['decision']>
export type DecisionInput = Pick<ManagerDecision, 'outcome' | 'reason' | 'feedback'> & {
  // What the finding's result should have been. Sent only for a corrected decision.
  reviewedResult?: AuditResult
}

export type { FindingReviewDetail } from '../../types/callReview'

export interface TeamReviewApi extends ManagerCallApi {
  listForManager(managerId: string): Promise<TeamConversation[]>
  saveDecision(
    managerId: string,
    conversationId: string,
    findingId: string,
    decision: DecisionInput,
  ): Promise<ManagerDecision>
}

export const decisionOutcomes = {
  confirmed: {
    label: 'Confirmed',
    description: 'The automatic feedback is correct.',
  },
  corrected: {
    label: 'Corrected',
    description: 'The feedback needs a correction, explained below.',
  },
  dismissed: {
    label: 'Dismissed',
    description: 'The feedback does not apply to this call.',
  },
  'cannot-assess': {
    label: 'Cannot assess',
    description: 'The evidence is not enough to decide.',
  },
} as const satisfies Record<ManagerDecision['outcome'], { label: string; description: string }>

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
      (second.flag?.requestedAt ?? second.date ?? '').localeCompare(
        first.flag?.requestedAt ?? first.date ?? '',
      ),
    )
}

export function findingReviewPath(conversation: TeamConversation, search = '') {
  return conversation.flag
    ? `/manager/conversations/${encodeURIComponent(conversation.id)}/findings/${encodeURIComponent(conversation.flag.findingId)}${search}`
    : null
}
