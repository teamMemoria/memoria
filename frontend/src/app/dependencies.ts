import type { CallApi } from '../types/callReview'
import { createDevCallApi } from '../lib/devCallApi'
import type { ViewerApi } from '../types/viewer'
import { createDevViewerApi } from '../lib/viewer'
import type { ConversationsApi } from '../features/conversations/conversations'
import { createDevConversationsApi } from '../features/conversations/devConversationsApi'

export function createDependencies(): {
  viewerApi: ViewerApi | null
  conversationsApi: ConversationsApi | null
  callApi: CallApi | null
} {
  if (import.meta.env.DEV) {
    const role =
      import.meta.env.VITE_DEV_ROLE === 'manager' ? 'manager' : 'agent'
    return {
      viewerApi: createDevViewerApi(role),
      conversationsApi: createDevConversationsApi(),
      callApi: createDevCallApi(),
    }
  }

  return { viewerApi: null, conversationsApi: null, callApi: null }
}
