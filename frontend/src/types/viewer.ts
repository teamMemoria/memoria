export type ViewerRole = 'agent' | 'manager'

export type Viewer = {
  id: string
  displayName: string
  role: ViewerRole
}

export interface ViewerApi {
  // profileId is the demo profile chosen on the entry screen, when there is one.
  getViewer(profileId?: string): Promise<Viewer | null>
}

export type DemoProfile = {
  id: string
  displayName: string
  role: ViewerRole
  // Conversations already imported for an Agent; null for Managers or when unknown.
  conversationCount: number | null
}

export interface DemoProfilesApi {
  listProfiles(): Promise<DemoProfile[]>
}
