import { ResourceNotice } from '../components/ResourceNotice'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import type { DemoProfile } from '../types/viewer'
import { useResource } from '../lib/useResource'
import { AppRoutes } from './routes'
import type { AppProps } from './dependencies'
import { EntryScreen } from '../features/entry/EntryScreen'
import {
  clearSelectedProfile,
  loadSelectedProfile,
  saveSelectedProfile,
} from '../lib/selectedProfile'

export default function App({
  viewerApi,
  profilesApi = null,
  ...workspace
}: AppProps) {
  // With a profiles API, the workspace opens as the profile chosen on the
  // entry screen; without one, as whoever the viewer API returns.
  const usesProfiles = viewerApi !== null && profilesApi !== null
  const [profileId, setProfileId] = useState(() =>
    usesProfiles ? loadSelectedProfile() : null,
  )
  const navigate = useNavigate()

  const read = useCallback(() => viewerApi!.getViewer(profileId ?? undefined), [viewerApi, profileId])
  const state = useResource(viewerApi && (!usesProfiles || profileId !== null) ? read : null)
  const viewer = state.status === 'ready' ? state.data : null
  const invalidProfile = usesProfiles && profileId !== null && (
    state.status === 'unavailable' || (viewer !== null && viewer.id !== profileId)
  )

  useEffect(() => {
    if (invalidProfile) clearSelectedProfile()
  }, [invalidProfile])

  function selectProfile(profile: DemoProfile) {
    saveSelectedProfile(profile.id)
    if (profile.id === profileId) state.retry()
    setProfileId(profile.id)
    void navigate(`/${profile.role}/conversations`)
  }

  function switchProfile() {
    clearSelectedProfile()
    setProfileId(null)
    void navigate('/')
  }

  if (usesProfiles && profilesApi && (profileId === null || invalidProfile))
    return (
      <EntryScreen
        api={profilesApi}
        notice={invalidProfile ? 'That profile is no longer available. Choose another.' : null}
        onSelect={selectProfile}
      />
    )

  if (viewer)
    return (
      <AppRoutes
        viewer={viewer}
        onSwitchProfile={usesProfiles ? switchProfile : undefined}
        {...workspace}
      />
    )

  return (
    <main className="startup">
      <h1>Memoria</h1>
      <ResourceNotice state={state} loading="Loading your workspace…" errorTitle="Unable to load your workspace"
        unavailableTitle="Your workspace is not available yet" unavailable="Sign-in has not been connected." />
    </main>
  )
}
