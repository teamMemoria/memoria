export type ViewerRole = 'agent' | 'manager'

export type Viewer = {
  id: string
  displayName: string
  role: ViewerRole
}

export interface ViewerApi {
  getViewer(): Promise<Viewer | null>
}
