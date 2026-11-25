import type { CallApi } from '../types/callReview'
import type {
  ApprovedKnowledgeApi,
  KnowledgeReviewApi,
} from '../types/knowledge'
import type { DemoProfilesApi, ViewerApi } from '../types/viewer'
import { createHttpApis } from '../lib/httpApi'
import { demoLoginEnabled, demoScorecardsEnabled } from '../lib/demoLogin'
import type { ConversationsApi } from '../features/conversations/conversations'
import type { TeamReviewApi } from '../features/review-queue/teamQueue'

export type WorkspaceDependencies = {
  conversationsApi: ConversationsApi | null
  callApi: CallApi | null
  knowledgeApi: ApprovedKnowledgeApi | null
  teamReviewApi: TeamReviewApi | null
  knowledgeReviewApi: KnowledgeReviewApi | null
}

type EntryDependencies = {
  viewerApi: ViewerApi | null
  profilesApi: DemoProfilesApi | null
}

export type AppDependencies = EntryDependencies & WorkspaceDependencies
export type AppProps = Pick<EntryDependencies, 'viewerApi'> & Partial<AppDependencies>

export function createDependencies(): AppDependencies {
  if (import.meta.env.VITE_API_BASE_URL ||
      (import.meta.env.DEV && import.meta.env.MODE !== 'test')) {
    const localSimulation = import.meta.env.MODE === 'simulation'
    const apis = createHttpApis(
      localSimulation ? '' : import.meta.env.VITE_API_BASE_URL ?? '',
      demoScorecardsEnabled(),
    )
    return { ...apis, profilesApi: demoLoginEnabled() ? apis.profilesApi : null }
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
