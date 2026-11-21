import type {
  DemoProfile,
  DemoProfilesApi,
  Viewer,
  ViewerApi,
  ViewerRole,
} from '../types/viewer'

const viewers: Record<ViewerRole, Viewer> = {
  agent: { id: 'agent-alex-morgan', displayName: 'Alex Morgan', role: 'agent' },
  manager: {
    id: 'manager-maya-chen',
    displayName: 'Maya Chen',
    role: 'manager',
  },
}

// The people in the development data, offered on the entry screen.
const devProfiles: DemoProfile[] = [
  { ...viewers.agent, conversationCount: null },
  {
    id: 'agent-sam-rivera',
    displayName: 'Sam Rivera',
    role: 'agent',
    conversationCount: null,
  },
  { ...viewers.manager, conversationCount: null },
]

export function createDevViewerApi(role: ViewerRole): ViewerApi {
  return {
    async getViewer(profileId) {
      if (profileId === undefined) return { ...viewers[role] }
      const profile = devProfiles.find((item) => item.id === profileId)
      if (!profile) return null
      return { id: profile.id, displayName: profile.displayName, role: profile.role }
    },
  }
}

export function createDevProfilesApi(): DemoProfilesApi {
  return {
    async listProfiles() {
      return devProfiles.map((profile) => ({ ...profile }))
    },
  }
}
