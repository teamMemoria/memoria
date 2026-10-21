export type ViewerRole = 'agent' | 'manager'

export type Viewer = {
  displayName: string
  role: ViewerRole
}

export interface ViewerApi {
  getViewer(): Promise<Viewer | null>
}
