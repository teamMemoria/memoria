import type { CallApi } from '../types/callReview'
import { createDevCallApi } from '../lib/devCallApi'
import type { ApprovedKnowledgeApi } from '../types/knowledge'
import { createDevApprovedKnowledgeApi } from '../lib/devApprovedKnowledge'
import type { ViewerApi } from '../types/viewer'
import { createDevViewerApi } from '../lib/viewer'
import type { ConversationsApi } from '../features/conversations/conversations'
import { createDevConversationsApi } from '../features/conversations/devConversationsApi'

export function createDependencies(): {
  viewerApi: ViewerApi | null
  conversationsApi: ConversationsApi | null
  callApi: CallApi | null
  knowledgeApi: ApprovedKnowledgeApi | null
} {
  if (import.meta.env.DEV) {
    const role =
      import.meta.env.VITE_DEV_ROLE === 'manager' ? 'manager' : 'agent'
    const callApi = createDevCallApi()
    return {
      viewerApi: createDevViewerApi(role),
      conversationsApi: createDevConversationsApi(callApi),
      callApi,
      knowledgeApi: createDevApprovedKnowledgeApi(),
    }
  }

  return {
    viewerApi: null,
    conversationsApi: null,
    callApi: null,
    knowledgeApi: null,
  }
}
