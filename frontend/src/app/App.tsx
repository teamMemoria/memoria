import type { CallApi } from '../types/callReview'
import type {
  ApprovedKnowledgeApi,
  KnowledgeReviewApi,
} from '../types/knowledge'
import { useEffect, useState } from 'react'
import type { Viewer, ViewerApi } from '../types/viewer'
import { Button, Panel } from '../components/controls'
import { AppRoutes } from './routes'
import type { ConversationsApi } from '../features/conversations/conversations'
import type { TeamReviewApi } from '../features/review-queue/teamQueue'

type ViewerState =
  | { status: 'loading' }
  | { status: 'ready'; viewer: Viewer }
  | { status: 'unavailable' }
  | { status: 'error' }

export default function App({
  viewerApi,
  conversationsApi = null,
  callApi = null,
  knowledgeApi = null,
  teamReviewApi = null,
  knowledgeReviewApi = null,
}: {
  viewerApi: ViewerApi | null
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

  useEffect(() => {
    let active = true

    if (!viewerApi) return

    void viewerApi.getViewer().then(
      (viewer) => {
        if (active)
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
  }, [viewerApi, attempt])

  if (state.status === 'ready')
    return (
      <AppRoutes
        viewer={state.viewer}
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
