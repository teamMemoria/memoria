import type { ReviewRequest } from '../../types/callReview'

export const automatedResultLabels = {
  'needs-review': 'Needs review',
  'meets-criteria': 'Meets criteria',
  'cannot-assess': 'Cannot assess',
  processing: 'Processing',
} as const

export const reviewStatusLabels = {
  'feedback-ready': 'Feedback ready',
  'review-requested': 'Review requested',
  'review-complete': 'Review complete',
} as const

export const conversationStatusLabels = {
  all: 'All statuses',
  ...reviewStatusLabels,
  processing: automatedResultLabels.processing,
}

export type AutomatedResult = keyof typeof automatedResultLabels
export type ReviewStatus = keyof typeof reviewStatusLabels

// The list status that matches an agent's review request.
export const reviewRequestStatuses = {
  requested: 'review-requested',
  complete: 'review-complete',
} as const satisfies Record<ReviewRequest['status'], ReviewStatus>
export type ConversationStatusFilter = keyof typeof conversationStatusLabels

export type Conversation = {
  id: string
  topic: string
  agentId: string
  agentName: string
  date: string
  automatedResult: AutomatedResult
  reviewStatus: ReviewStatus | null
}

export interface ConversationsApi {
  listForAgent(agentId: string): Promise<Conversation[]>
}

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeZone: 'UTC',
})

export function formatConversationDate(date: string) {
  return dateFormatter.format(new Date(`${date}T00:00:00Z`))
}

export function getAgentConversations(
  conversations: Conversation[],
  agentId: string,
) {
  return conversations
    .filter((conversation) => conversation.agentId === agentId)
    .sort((first, second) => second.date.localeCompare(first.date))
}

export function filterConversations(
  conversations: Conversation[],
  { query, status }: { query: string; status: ConversationStatusFilter },
) {
  const search = query.trim().toLowerCase()

  return conversations.filter((conversation) => {
    const statusMatches =
      status === 'all' ||
      (status === 'processing'
        ? conversation.automatedResult === 'processing'
        : conversation.reviewStatus === status)
    const searchableText = [
      conversation.id,
      conversation.topic,
      conversation.agentName,
      conversation.date,
      formatConversationDate(conversation.date),
      automatedResultLabels[conversation.automatedResult],
      conversation.reviewStatus &&
        reviewStatusLabels[conversation.reviewStatus],
    ]
      .join(' ')
      .toLowerCase()

    return statusMatches && searchableText.includes(search)
  })
}

export function countConversationStatuses(conversations: Conversation[]) {
  const counts = {
    reviewComplete: 0,
    feedbackReady: 0,
    reviewRequested: 0,
    processing: 0,
  }

  for (const conversation of conversations) {
    if (conversation.automatedResult === 'processing') counts.processing += 1
    else if (conversation.reviewStatus === 'review-complete') {
      counts.reviewComplete += 1
    } else if (conversation.reviewStatus === 'review-requested') {
      counts.reviewRequested += 1
    } else if (conversation.reviewStatus === 'feedback-ready') {
      counts.feedbackReady += 1
    }
  }

  return counts
}
