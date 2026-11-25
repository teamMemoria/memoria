import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import type { Viewer } from '../../types/viewer'
import { conversationStatusLabels, getAgentConversations, type Conversation, type ConversationsApi, type ConversationStatusFilter } from './conversations'

type LoadState = {
  api: ConversationsApi | null
  agentId: string
} & (
  | { status: 'loading' }
  | { status: 'ready'; records: Conversation[] }
  | { status: 'error' }
)

const filters = Object.entries(conversationStatusLabels)

export function useConversations(viewer: Viewer, api: ConversationsApi | null) {
  const [loaded, setLoaded] = useState<LoadState>({
    api,
    agentId: viewer.id,
    status: 'loading',
  })
  const [attempt, setAttempt] = useState(0)
  const [previewStatus, setPreviewStatus] =
    useState<ConversationStatusFilter | null>(null)
  const [params, setParams] = useSearchParams()
  const query = params.get('q') ?? ''
  const requestedStatus = params.get('status')
  const status = (filters.find(
    ([value]) => value === requestedStatus,
  )?.[0] ?? 'all') as ConversationStatusFilter
  const search = params.size ? `?${params}` : ''
  const state = !api
    ? { status: 'error' as const }
    : loaded.api === api && loaded.agentId === viewer.id
      ? loaded
      : { status: 'loading' as const }

  useEffect(() => {
    let active = true
    if (!api) return
    void api.listForAgent(viewer.id).then(
      (records) => {
        if (active)
          setLoaded({
            api,
            agentId: viewer.id,
            status: 'ready',
            records: getAgentConversations(records, viewer.id),
          })
      },
      () => {
        if (active) setLoaded({ api, agentId: viewer.id, status: 'error' })
      },
    )
    return () => {
      active = false
    }
  }, [api, viewer.id, attempt])

  function changeFilter(key: string, value: string, replace = false) {
    if (key === 'status') setPreviewStatus(null)
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        if (!value || (key === 'status' && value === 'all')) next.delete(key)
        else next.set(key, value)
        return next
      },
      { replace },
    )
  }

  return { state, setLoaded, setAttempt, previewStatus, setPreviewStatus, query, status, requestedStatus, search, changeFilter, setParams }
}
