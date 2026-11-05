import type { CallApi } from '../types/callReview'
import { createDevCallApi } from '../lib/devCallApi'
import type {
  ApprovedKnowledgeApi,
  KnowledgeReviewApi,
} from '../types/knowledge'
import { createDevApprovedKnowledgeApi } from '../lib/devApprovedKnowledge'
import { createDevKnowledgeReviewApi } from '../lib/devKnowledgeReview'
import type { ViewerApi } from '../types/viewer'
import { createDevViewerApi } from '../lib/viewer'
import type { ConversationsApi } from '../features/conversations/conversations'
import { createDevConversationsApi } from '../features/conversations/devConversationsApi'
import type { TeamReviewApi } from '../features/review-queue/teamQueue'
import { createDevTeamReviewApi } from '../features/review-queue/devTeamReviewApi'

export function createDependencies(): {
  viewerApi: ViewerApi | null
  conversationsApi: ConversationsApi | null
  callApi: CallApi | null
  knowledgeApi: ApprovedKnowledgeApi | null
  teamReviewApi: TeamReviewApi | null
  knowledgeReviewApi: KnowledgeReviewApi | null
} {
  if (import.meta.env.DEV) {
    const role =
      import.meta.env.VITE_DEV_ROLE === 'manager' ? 'manager' : 'agent'
    const callApi = createDevCallApi()
    const knowledgeReviewApi = createDevKnowledgeReviewApi()
    return {
      viewerApi: createDevViewerApi(role),
      conversationsApi: createDevConversationsApi(callApi),
      callApi,
      knowledgeApi: createDevApprovedKnowledgeApi(knowledgeReviewApi),
      teamReviewApi: createDevTeamReviewApi(callApi),
      knowledgeReviewApi,
    }
  }

  return {
    viewerApi: null,
    conversationsApi: null,
    callApi: null,
    knowledgeApi: null,
    teamReviewApi: null,
    knowledgeReviewApi: null,
  }
}
