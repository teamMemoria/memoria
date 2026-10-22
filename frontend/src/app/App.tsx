import { useEffect, useState } from 'react'
import type { Viewer, ViewerApi } from '../types/viewer'
import { Button, Panel } from '../components/controls'
import { AppRoutes } from './routes'

type ViewerState =
  | { status: 'loading' }
  | { status: 'ready'; viewer: Viewer }
  | { status: 'unavailable' }
  | { status: 'error' }

export default function App({ viewerApi }: { viewerApi: ViewerApi | null }) {
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

  if (state.status === 'ready') return <AppRoutes viewer={state.viewer} />

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
