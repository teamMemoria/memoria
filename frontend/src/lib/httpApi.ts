import type {
  CallApi,
  CallReview,
  AgentContext,
  ReviewRequest,
  TranscriptTurn,
} from '../types/callReview'
import type {
  Viewer,
  ViewerApi,
  DemoProfile,
  DemoProfilesApi,
} from '../types/viewer'
import type {
  ApprovedKnowledgeApi,
  KnowledgeEntry,
  KnowledgeReviewApi,
  KnowledgeDraft,
  KnowledgeReviewDetail,
} from '../types/knowledge'
import type {
  Conversation,
  ConversationsApi,
} from '../features/conversations/conversations'
import type {
  FindingReviewDetail,
  ManagerDecision,
  TeamConversation,
  TeamReviewApi,
} from '../features/review-queue/teamQueue'

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
    if (
      missing &&
      (response.status === 404 ||
        (path === '/api/viewer' && response.status === 401))
    )
      return null as T
    if (!response.ok) throw new Error('The request could not be completed.')
    return response.json() as Promise<T>
  }
  const callPath = (id: string) =>
    `/api/agent/conversations/${encodeURIComponent(id)}`
  const managerPath = (id: string) =>
    `/api/manager/conversations/${encodeURIComponent(id)}`
  async function narration(
    role: 'agent' | 'manager',
    userId: string,
    id: string,
    turn: TranscriptTurn,
    voice: string,
    signal: AbortSignal,
  ): Promise<Blob> {
    if (import.meta.env.DEV && !userId)
      throw new Error('Choose a profile before playback.')
    const digest = await crypto.subtle.digest(
      'SHA-256',
      new TextEncoder().encode(turn.text),
    )
    const hash = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, '0'),
    ).join('')
    const query = new URLSearchParams({ voice, text_sha256: hash })
    const response = await fetch(
      `${base}/api/${role}/conversations/${encodeURIComponent(id)}/turns/${turn.number}/narration?${query}`,
      {
        credentials: 'include',
        signal,
        headers: import.meta.env.DEV ? { 'X-Dev-User': userId } : {},
      },
    )
    if (response.status === 409)
      throw new Error('Transcript changed. Refresh before playing narration.')
    if (response.status === 503)
      throw new Error('Natural voice is not prepared for this passage yet.')
    if (
      !response.ok ||
      !response.headers.get('Content-Type')?.startsWith('audio/mpeg')
    )
      throw new Error('Narration unavailable for this conversation.')
    return response.blob()
  }
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
    listForAgent: (userId) =>
      request<Conversation[]>(userId, '/api/agent/conversations'),
  }
  const callApi: CallApi = {
    getNarration: (...args) => narration('agent', ...args),
    getCallForAgent: (userId, id) =>
      request<CallReview | null>(userId, callPath(id), undefined, 'GET', true),
    saveContext: (userId, id, text) =>
      request<AgentContext>(userId, `${callPath(id)}/context`, { text }, 'PUT'),
    requestReview: (userId, id, findingId, reason) =>
      request<ReviewRequest>(
        userId,
        `${callPath(id)}/review-requests`,
        { findingId, reason },
        'POST',
      ),
  }
  const knowledgeApi: ApprovedKnowledgeApi = {
    listForAgent: (userId) =>
      request<KnowledgeEntry[]>(userId, '/api/agent/knowledge'),
    getForAgent: (userId, id) =>
      request<KnowledgeEntry | null>(
        userId,
        `/api/agent/knowledge/${encodeURIComponent(id)}`,
        undefined,
        'GET',
        true,
      ),
  }
  const teamReviewApi: TeamReviewApi = {
    getNarration: (...args) => narration('manager', ...args),
    listForManager: (userId) =>
      request<TeamConversation[]>(userId, '/api/manager/conversations'),
    getCallForManager: (userId, id) =>
      request<FindingReviewDetail | null>(
        userId,
        managerPath(id),
        undefined,
        'GET',
        true,
      ),
    saveDecision: (userId, id, findingId, decision) =>
      request<ManagerDecision>(
        userId,
        `${managerPath(id)}/findings/${encodeURIComponent(findingId)}/decision`,
        decision,
        'POST',
      ),
  }
  const draftPath = (id: string) =>
    `/api/manager/knowledge/drafts/${encodeURIComponent(id)}`
  const knowledgeReviewApi: KnowledgeReviewApi = {
    listForManager: (userId) =>
      request<KnowledgeDraft[]>(userId, '/api/manager/knowledge/drafts'),
    getForManager: (userId, id) =>
      request<KnowledgeReviewDetail | null>(
        userId,
        draftPath(id),
        undefined,
        'GET',
        true,
      ),
    approve: (userId, id, verifiedReferenceUrl, version) =>
      request<KnowledgeDraft>(
        userId,
        `${draftPath(id)}/approve`,
        { verifiedReferenceUrl, version },
        'POST',
      ),
    reject: (userId, id, reason, version) =>
      request<KnowledgeDraft>(
        userId,
        `${draftPath(id)}/reject`,
        { reason, version },
        'POST',
      ),
  }
  return {
    viewerApi,
    profilesApi,
    conversationsApi,
    callApi,
    knowledgeApi,
    teamReviewApi,
    knowledgeReviewApi,
  }
}
