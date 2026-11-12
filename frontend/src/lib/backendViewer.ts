import type { DemoProfilesApi, ViewerApi } from '../types/viewer'

// Demo sign-in against the backend: the chosen profile is sent as X-Dev-User,
// and the backend decides what that profile may see.

export function createBackendProfilesApi(): DemoProfilesApi {
  return {
    async listProfiles() {
      const response = await fetch('/api/demo/profiles')
      if (!response.ok) throw new Error(`Profiles request failed: ${response.status}`)
      return response.json()
    },
  }
}

export function createBackendViewerApi(): ViewerApi {
  return {
    async getViewer(profileId) {
      if (profileId === undefined) return null
      const response = await fetch('/api/viewer', {
        headers: { 'X-Dev-User': profileId },
      })
      // An unknown or removed profile: the entry screen asks for another one.
      if (response.status === 401 || response.status === 404) return null
      if (!response.ok) throw new Error(`Viewer request failed: ${response.status}`)
      return response.json()
    },
  }
}
