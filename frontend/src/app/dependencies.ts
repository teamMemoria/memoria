import type { ViewerApi } from '../types/viewer'
import { createDevViewerApi } from '../lib/viewer'
import type { ConversationsApi } from '../features/conversations/conversations'
import { createDevConversationsApi } from '../features/conversations/devConversationsApi'

export function createDependencies(): {
  viewerApi: ViewerApi | null
  conversationsApi: ConversationsApi | null
} {
  if (import.meta.env.DEV) {
    const role =
      import.meta.env.VITE_DEV_ROLE === 'manager' ? 'manager' : 'agent'
    return {
      viewerApi: createDevViewerApi(role),
      conversationsApi: createDevConversationsApi(),
    }
  }

  return { viewerApi: null, conversationsApi: null }
}
