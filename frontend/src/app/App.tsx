import type { CallApi } from '../types/callReview'
import type {
  ApprovedKnowledgeApi,
  KnowledgeReviewApi,
} from '../types/knowledge'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import type {
  DemoProfile,
  DemoProfilesApi,
  Viewer,
  ViewerApi,
} from '../types/viewer'
import { Button, Panel } from '../components/controls'
import { AppRoutes } from './routes'
import type { ConversationsApi } from '../features/conversations/conversations'
import type { TeamReviewApi } from '../features/review-queue/teamQueue'
import { EntryScreen } from '../features/entry/EntryScreen'
import {
  clearSelectedProfile,
  loadSelectedProfile,
  saveSelectedProfile,
} from '../lib/selectedProfile'

type ViewerState =
  | { status: 'loading' }
  | { status: 'ready'; viewer: Viewer }
  | { status: 'unavailable' }
  | { status: 'error' }

export default function App({
  viewerApi,
  profilesApi = null,
  conversationsApi = null,
  callApi = null,
  knowledgeApi = null,
  teamReviewApi = null,
  knowledgeReviewApi = null,
}: {
  viewerApi: ViewerApi | null
  profilesApi?: DemoProfilesApi | null
  conversationsApi?: ConversationsApi | null
  callApi?: CallApi | null
  knowledgeApi?: ApprovedKnowledgeApi | null
  teamReviewApi?: TeamReviewApi | null
  knowledgeReviewApi?: KnowledgeReviewApi | null
}) {
  const [state, setState] = useState<ViewerState>(
    viewerApi ? { status: 'loading' } : { status: 'unavailable' },
  )
  const [attempt, setAttempt] = useState(0)
  // With a profiles API, the workspace opens as the profile chosen on the
  // entry screen; without one, as whoever the viewer API returns.
  const usesProfiles = viewerApi !== null && profilesApi !== null
  const [profileId, setProfileId] = useState(() =>
    usesProfiles ? loadSelectedProfile() : null,
  )
  const [notice, setNotice] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    let active = true

    if (!viewerApi) return
    if (usesProfiles && profileId === null) return

    void viewerApi.getViewer(profileId ?? undefined).then(
      (viewer) => {
        if (!active) return
        // A stored profile that no longer exists, or resolves to someone
        // else, never opens a workspace.
        if (usesProfiles && viewer?.id !== profileId) {
          clearSelectedProfile()
          setProfileId(null)
          setNotice('That profile is no longer available. Choose another.')
          return
        }
        setState(
          viewer ? { status: 'ready', viewer } : { status: 'unavailable' },
        )
      },
      () => {
        if (active) setState({ status: 'error' })
      },
    )

    return () => {
      active = false
    }
  }, [viewerApi, usesProfiles, profileId, attempt])

  function selectProfile(profile: DemoProfile) {
    saveSelectedProfile(profile.id)
    setNotice(null)
    setState({ status: 'loading' })
    setProfileId(profile.id)
    void navigate(`/${profile.role}/conversations`)
  }

  function switchProfile() {
    clearSelectedProfile()
    setState({ status: 'loading' })
    setProfileId(null)
    void navigate('/')
  }

  if (usesProfiles && profilesApi && profileId === null)
    return (
      <EntryScreen
        api={profilesApi}
        notice={notice}
        onSelect={selectProfile}
      />
    )

  if (state.status === 'ready')
    return (
      <AppRoutes
        viewer={state.viewer}
        onSwitchProfile={usesProfiles ? switchProfile : undefined}
        conversationsApi={conversationsApi}
        callApi={callApi}
        knowledgeApi={knowledgeApi}
        teamReviewApi={teamReviewApi}
        knowledgeReviewApi={knowledgeReviewApi}
      />
    )

  return (
    <main className="startup">
      <h1>Memoria</h1>
      {state.status === 'loading' && (
        <p role="status">Loading your workspace…</p>
      )}
      {state.status === 'unavailable' && (
        <Panel title="Your workspace is not available yet">
          <p>Sign-in has not been connected.</p>
        </Panel>
      )}
      {state.status === 'error' && (
        <Panel title="Unable to load your workspace">
          <p role="alert">Please try again.</p>
          <Button
            onClick={() => {
              setState({ status: 'loading' })
              setAttempt((value) => value + 1)
            }}
          >
            Try again
          </Button>
        </Panel>
      )}
    </main>
  )
}
