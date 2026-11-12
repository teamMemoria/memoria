import type { CallApi } from '../types/callReview'
import { createDevCallApi } from '../lib/devCallApi'
import type {
  ApprovedKnowledgeApi,
  KnowledgeReviewApi,
} from '../types/knowledge'
import { createDevApprovedKnowledgeApi } from '../lib/devApprovedKnowledge'
import { createDevKnowledgeReviewApi } from '../lib/devKnowledgeReview'
import type { DemoProfilesApi, ViewerApi } from '../types/viewer'
import { createDevProfilesApi, createDevViewerApi } from '../lib/viewer'
import { createHttpApis } from '../lib/httpApi'
import type { ConversationsApi } from '../features/conversations/conversations'
import { createDevConversationsApi } from '../features/conversations/devConversationsApi'
import type { TeamReviewApi } from '../features/review-queue/teamQueue'
import { createDevTeamReviewApi } from '../features/review-queue/devTeamReviewApi'

export function createDependencies(): {
  viewerApi: ViewerApi | null
  profilesApi: DemoProfilesApi | null
  conversationsApi: ConversationsApi | null
  callApi: CallApi | null
  knowledgeApi: ApprovedKnowledgeApi | null
  teamReviewApi: TeamReviewApi | null
  knowledgeReviewApi: KnowledgeReviewApi | null
} {
  if (import.meta.env.VITE_API_BASE_URL ||
      (import.meta.env.DEV && import.meta.env.VITE_DEMO_BACKEND === 'true')) {
    const apis = createHttpApis(import.meta.env.VITE_API_BASE_URL ?? '')
    return { ...apis, profilesApi: import.meta.env.DEV ? apis.profilesApi : null }
  }

  if (import.meta.env.DEV) {
    const role =
      import.meta.env.VITE_DEV_ROLE === 'manager' ? 'manager' : 'agent'
    const callApi = createDevCallApi()
    const knowledgeReviewApi = createDevKnowledgeReviewApi()
    return {
      viewerApi: createDevViewerApi(role),
      profilesApi: createDevProfilesApi(),
      conversationsApi: createDevConversationsApi(callApi),
      callApi,
      knowledgeApi: createDevApprovedKnowledgeApi(knowledgeReviewApi),
      teamReviewApi: createDevTeamReviewApi(callApi),
      knowledgeReviewApi,
    }
  }

  return {
    viewerApi: null,
    profilesApi: null,
    conversationsApi: null,
    callApi: null,
    knowledgeApi: null,
    teamReviewApi: null,
    knowledgeReviewApi: null,
  }
}
