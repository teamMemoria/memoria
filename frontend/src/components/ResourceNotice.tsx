import { Button, Panel } from './controls'

export function ResourceNotice({ state, loading, errorTitle, error = 'Please try again.',
  unavailableTitle, unavailable }: {
  state: { status: 'loading' | 'error' | 'unavailable' | 'ready'; retry: () => void }
  loading: string
  errorTitle: string
  error?: string
  unavailableTitle: string
  unavailable: string
}) {
  switch (state.status) {
    case 'loading':
      return <p role="status">{loading}</p>
    case 'error':
      return (
        <Panel title={errorTitle}>
          <p role="alert">{error}</p>
          <Button onClick={state.retry}>Try again</Button>
        </Panel>
      )
    case 'ready':
    case 'unavailable':
      return <Panel title={unavailableTitle}><p>{unavailable}</p></Panel>
  }
}
