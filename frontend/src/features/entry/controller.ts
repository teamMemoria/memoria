import { useEffect, useState } from 'react'
import type { DemoProfile, DemoProfilesApi, ViewerRole } from '../../types/viewer'

type ProfilesState =
  | { status: 'loading' }
  | { status: 'ready'; profiles: DemoProfile[] }
  | { status: 'error' }

export function useEntry(api: DemoProfilesApi) {
  const [state, setState] = useState<ProfilesState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [role, setRole] = useState<ViewerRole>('agent')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void api.listProfiles().then(
      (profiles) => {
        if (active) setState({ status: 'ready', profiles })
      },
      () => {
        if (active) setState({ status: 'error' })
      },
    )
    return () => {
      active = false
    }
  }, [api, attempt])

  const profiles =
    state.status === 'ready'
      ? state.profiles.filter((profile) => profile.role === role)
      : []
  const selected = profiles.find((profile) => profile.id === selectedId)

  return { state, setState, setAttempt, role, setRole, selectedId, setSelectedId, profiles, selected }
}
