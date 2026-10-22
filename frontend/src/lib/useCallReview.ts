import { useEffect, useState } from 'react'
import type { CallApi, CallReview } from '../types/callReview'

type CallState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'unavailable' }
  | { status: 'ready'; call: CallReview }

export function useCallReview(
  api: CallApi | null,
  agentId: string,
  conversationId: string,
) {
  const [request, setRequest] = useState<{
    api: CallApi | null
    agentId: string
    conversationId: string
    state: CallState
  }>({
    api,
    agentId,
    conversationId,
    state: { status: 'loading' },
  })
  const [attempt, setAttempt] = useState(0)
  const state: CallState = !api
    ? { status: 'unavailable' }
    : request.api === api &&
        request.agentId === agentId &&
        request.conversationId === conversationId
      ? request.state
      : { status: 'loading' }

  useEffect(() => {
    let active = true
    if (!api) return
    void api.getCallForAgent(agentId, conversationId).then(
      (call) => {
        if (active)
          setRequest({
            api,
            agentId,
            conversationId,
            state:
              call && call.agentId === agentId && call.id === conversationId
                ? { status: 'ready', call }
                : { status: 'unavailable' },
          })
      },
      () => {
        if (active)
          setRequest({
            api,
            agentId,
            conversationId,
            state: { status: 'error' },
          })
      },
    )
    return () => {
      active = false
    }
  }, [api, agentId, conversationId, attempt])

  function retry() {
    setRequest({ api, agentId, conversationId, state: { status: 'loading' } })
    setAttempt((value) => value + 1)
  }

  return { ...state, retry }
}
