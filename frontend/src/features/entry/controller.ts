import { useCallback, useState } from 'react'
import { useResource } from '../../lib/useResource'
import type { DemoProfilesApi, ViewerRole } from '../../types/viewer'

export function useEntry(api: DemoProfilesApi) {
  const read = useCallback(() => api.listProfiles(), [api])
  const state = useResource(read)
  const [role, setRole] = useState<ViewerRole>('agent')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const profiles =
    state.status === 'ready'
      ? state.data.filter((profile) => profile.role === role)
      : []
  const selected = profiles.find((profile) => profile.id === selectedId)

  return { state, role, setRole, selectedId, setSelectedId, profiles, selected }
}
