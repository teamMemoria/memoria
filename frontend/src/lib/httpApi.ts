import type { CallApi, CallReview, AgentContext, ReviewRequest } from '../types/callReview'
import type { Viewer, ViewerApi, DemoProfile, DemoProfilesApi } from '../types/viewer'
import type { ApprovedKnowledgeApi, KnowledgeEntry, KnowledgeReviewApi, KnowledgeDraft, KnowledgeReviewDetail } from '../types/knowledge'
import type { Conversation, ConversationsApi } from '../features/conversations/conversations'
import type { FindingReviewDetail, ManagerDecision, TeamConversation, TeamReviewApi } from '../features/review-queue/teamQueue'

// The selected, server-validated viewer is passed by each screen. No global
// identity or localStorage lookup can change the owner of an in-flight request.
// X-Dev-User is only for the backend's explicitly enabled local demo mode.
export function createHttpApis(baseUrl = '') {
  const base = baseUrl.replace(/\/$/, '')
  async function request<T>(
    userId: string | undefined,
    path: string,
    body?: object,
    method = 'GET',
    missing = false,
  ): Promise<T> {
    if (import.meta.env.DEV && !userId && path !== '/api/demo/profiles')
      throw new Error('Choose a profile before opening its workspace.')
    const response = await fetch(`${base}${path}`, {
      method,
      credentials: 'include',
      signal: AbortSignal.timeout(15000),
      headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...(import.meta.env.DEV && userId ? { 'X-Dev-User': userId } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    })
    if (missing && (response.status === 404 || (path === '/api/viewer' && response.status === 401)))
      return null as T
    if (!response.ok) throw new Error('The request could not be completed.')
    return response.json() as Promise<T>
  }
  const callPath = (id: string) => `/api/agent/conversations/${encodeURIComponent(id)}`
  const managerPath = (id: string) => `/api/manager/conversations/${encodeURIComponent(id)}`
  const draftPath = (id: string) => `/api/manager/knowledge/drafts/${encodeURIComponent(id)}`
  const viewerApi: ViewerApi = {
    getViewer: async (id) => {
      if (import.meta.env.DEV && !id) return null
      return request<Viewer | null>(id, '/api/viewer', undefined, 'GET', true)
    },
  }
  const profilesApi: DemoProfilesApi = {
    listProfiles: () => request<DemoProfile[]>(undefined, '/api/demo/profiles'),
  }
  const conversationsApi: ConversationsApi = {
    listForAgent: (id) => request<Conversation[]>(id, '/api/agent/conversations'),
  }
  const callApi: CallApi = {
    getCallForAgent: (id, callId) => request<CallReview | null>(id, callPath(callId), undefined, 'GET', true),
    saveContext: (id, callId, text) => request<AgentContext>(id, `${callPath(callId)}/context`, { text }, 'PUT'),
    requestReview: (id, callId, findingId, reason) => request<ReviewRequest>(id, `${callPath(callId)}/review-requests`, { findingId, reason }, 'POST'),
  }
  const knowledgeApi: ApprovedKnowledgeApi = {
    listForAgent: (id) => request<KnowledgeEntry[]>(id, '/api/agent/knowledge'),
    getForAgent: (id, entryId) => request<KnowledgeEntry | null>(id, `/api/agent/knowledge/${encodeURIComponent(entryId)}`, undefined, 'GET', true),
  }
  const teamReviewApi: TeamReviewApi = {
    listForManager: (id) => request<TeamConversation[]>(id, '/api/manager/conversations'),
    getCallForManager: (id, callId) => request<FindingReviewDetail | null>(id, managerPath(callId), undefined, 'GET', true),
    saveDecision: (id, callId, findingId, decision) => request<ManagerDecision>(id, `${managerPath(callId)}/findings/${encodeURIComponent(findingId)}/decision`, decision, 'POST'),
  }
  const knowledgeReviewApi: KnowledgeReviewApi = {
    listForManager: (id) => request<KnowledgeDraft[]>(id, '/api/manager/knowledge/drafts'),
    getForManager: (id, entryId) => request<KnowledgeReviewDetail | null>(id, draftPath(entryId), undefined, 'GET', true),
    decisionsAvailable: false,
    approve: async () => { throw new Error('Knowledge decisions are not available yet.') },
    reject: async () => { throw new Error('Knowledge decisions are not available yet.') },
  }
  return { viewerApi, profilesApi, conversationsApi, callApi, knowledgeApi, teamReviewApi, knowledgeReviewApi }
}
