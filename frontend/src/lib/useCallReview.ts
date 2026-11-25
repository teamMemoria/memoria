import { useCallback } from 'react'
import type { CallApi, CallReview, ManagerCallApi } from '../types/callReview'
import { useResource } from './useResource'

export function useCallReview(
  api: CallApi | null,
  viewerId: string,
  conversationId: string,
  managerApi: ManagerCallApi | null = null,
) {
  const read = useCallback(async () => {
    if (managerApi) {
      const detail = await managerApi.getCallForManager(viewerId, conversationId)
      return detail?.call.id === conversationId ? detail : null
    }
    const call = await api?.getCallForAgent(viewerId, conversationId)
    return call?.id === conversationId && call.agentId === viewerId ? { call, canDecide: false } : null
  }, [api, managerApi, viewerId, conversationId])
  const state = useResource(api || managerApi ? read : null)
  if (state.status !== 'ready') return state
  return {
    status: state.status,
    ...state.data,
    retry: state.retry,
    update: (changes: Partial<CallReview>) =>
      state.update((detail) => ({ ...detail, call: { ...detail.call, ...changes } })),
  }
}
