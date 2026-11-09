import type { Viewer, ViewerApi, ViewerRole } from '../types/viewer'

const viewers: Record<ViewerRole, Viewer> = {
  agent: { id: 'agent-alex-morgan', displayName: 'Alex Morgan', role: 'agent' },
  manager: {
    id: 'manager-maya-chen',
    displayName: 'Maya Chen',
    role: 'manager',
  },
}

export function createDevViewerApi(role: ViewerRole): ViewerApi {
  return {
    async getViewer() {
      return { ...viewers[role] }
    },
  }
}
