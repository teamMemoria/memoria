import type { ViewerApi } from '../types/viewer'
import { createDevViewerApi } from '../lib/viewer'

export function createDependencies(): { viewerApi: ViewerApi | null } {
  if (import.meta.env.DEV) {
    const role =
      import.meta.env.VITE_DEV_ROLE === 'manager' ? 'manager' : 'agent'
    return { viewerApi: createDevViewerApi(role) }
  }

  return { viewerApi: null }
}
