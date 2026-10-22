import type { Viewer, ViewerApi, ViewerRole } from '../types/viewer'

const viewers: Record<ViewerRole, Viewer> = {
  agent: { displayName: 'Alex Morgan', role: 'agent' },
  manager: { displayName: 'Maya Chen', role: 'manager' },
}

export function createDevViewerApi(role: ViewerRole): ViewerApi {
  return {
    async getViewer() {
      return { ...viewers[role] }
    },
  }
}
