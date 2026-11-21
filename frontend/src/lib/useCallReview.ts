import { useEffect, useState } from 'react'
import type { CallApi, CallReview, ManagerCallApi } from '../types/callReview'

type CallState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'unavailable' }
  | { status: 'ready'; call: CallReview }

export function useCallReview(
  api: CallApi | null,
  viewerId: string,
  conversationId: string,
  managerApi: ManagerCallApi | null = null,
) {
  const [request, setRequest] = useState<{
    api: CallApi | null
    managerApi: ManagerCallApi | null
    viewerId: string
    conversationId: string
    state: CallState
  }>({
    api,
    managerApi,
    viewerId,
    conversationId,
    state: { status: 'loading' },
  })
  const [attempt, setAttempt] = useState(0)
  const isCurrentRequest =
    request.api === api &&
    request.managerApi === managerApi &&
    request.viewerId === viewerId &&
    request.conversationId === conversationId

  if (!isCurrentRequest) {
    setRequest({
      api,
      managerApi,
      viewerId,
      conversationId,
      state: { status: 'loading' },
    })
  }

  const state: CallState =
    !api && !managerApi
      ? { status: 'unavailable' }
      : isCurrentRequest
        ? request.state
        : { status: 'loading' }

  useEffect(() => {
    let active = true
    if (!api && !managerApi) return
    const pending = managerApi
      ? managerApi
          .getCallForManager(viewerId, conversationId)
          .then((detail) => detail?.call ?? null)
      : api!.getCallForAgent(viewerId, conversationId)
    void pending.then(
      (call) => {
        if (active)
          setRequest({
            api,
            managerApi,
            viewerId,
            conversationId,
            state:
              call &&
              (managerApi || call.agentId === viewerId) &&
              call.id === conversationId
                ? { status: 'ready', call }
                : { status: 'unavailable' },
          })
      },
      () => {
        if (active)
          setRequest({
            api,
            managerApi,
            viewerId,
            conversationId,
            state: { status: 'error' },
          })
      },
    )
    return () => {
      active = false
    }
  }, [api, managerApi, viewerId, conversationId, attempt])

  function retry() {
    setRequest({
      api,
      managerApi,
      viewerId,
      conversationId,
      state: { status: 'loading' },
    })
    setAttempt((value) => value + 1)
  }

  // Shows a successful save without reloading the whole call.
  function update(changes: Partial<CallReview>) {
    setRequest((current) =>
      current.state.status === 'ready'
        ? {
            ...current,
            state: {
              status: 'ready',
              call: { ...current.state.call, ...changes },
            },
          }
        : current,
    )
  }

  return { ...state, retry, update }
}
