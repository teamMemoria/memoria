import { createHttpApis } from './httpApi'

// Compatibility exports for callers of the original demo-login adapter.
export function createBackendProfilesApi() {
  return createHttpApis().profilesApi
}

export function createBackendViewerApi() {
  return createHttpApis().viewerApi
}
