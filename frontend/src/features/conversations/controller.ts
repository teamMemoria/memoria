import { useWorkspaceSearch } from '../../lib/workspaceSearch'
import { useResource } from '../../lib/useResource'
import { useCallback, useState } from 'react'
import type { Viewer } from '../../types/viewer'
import { conversationStatusLabels, getAgentConversations, type ConversationsApi, type ConversationStatusFilter } from './conversations'

const filters = Object.entries(conversationStatusLabels)

export function useConversations(viewer: Viewer, api: ConversationsApi | null) {
  const [previewStatus, setPreviewStatus] =
    useState<ConversationStatusFilter | null>(null)
  const { params, filter, setParams, query, search } = useWorkspaceSearch({ status: 'all' })
  const requestedStatus = params.get('status')
  const status = (filters.find(
    ([value]) => value === requestedStatus,
  )?.[0] ?? 'all') as ConversationStatusFilter
  const read = useCallback(async () =>
    getAgentConversations(await api!.listForAgent(viewer.id), viewer.id), [api, viewer.id])
  const state = useResource(api ? read : null)

  function changeFilter(key: string, value: string, replace = false) {
    if (key === 'status') setPreviewStatus(null)
    filter(key, value, replace)
  }

  return { state, previewStatus, setPreviewStatus, query, status, requestedStatus, search, changeFilter, setParams }
}
