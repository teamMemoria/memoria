import type { CallApi, TranscriptTurn } from '../types/callReview'
import type { DemoProfilesApi, ViewerApi } from '../types/viewer'
import type { ApprovedKnowledgeApi, KnowledgeReviewApi } from '../types/knowledge'
import type { ConversationsApi } from '../features/conversations/conversations'
import type { TeamReviewApi } from '../features/review-queue/teamQueue'
import { demoLoginEnabled } from './demoLogin'

export function createHttpApis(baseUrl = '', simulation = false) {
  const base = baseUrl.replace(/\/$/, '')
  async function request<T>(
    userId: string | undefined,
    path: string,
    body?: object,
    method = 'GET',
    missing = false,
  ): Promise<T> {
    if (demoLoginEnabled() && !userId && path !== '/api/demo/profiles')
      throw new Error('Choose a profile before opening its workspace.')
    const response = await fetch(`${base}${path}`, {
      method,
      credentials: 'include',
      signal: AbortSignal.timeout(15000),
      headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...(demoLoginEnabled() && userId ? { 'X-Dev-User': userId } : {}),
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
  const optional = <T>(user: string, path: string) => request<T | null>(user, path, undefined, 'GET', true)
  const callPath = (role: 'agent' | 'manager', id: string) =>
    `/api/${role}/conversations/${encodeURIComponent(id)}`
  const draftPath = (id: string) => `/api/manager/knowledge/drafts/${encodeURIComponent(id)}`

  async function narration(
    role: 'agent' | 'manager',
    userId: string,
    id: string,
    turn: TranscriptTurn,
    voice: string,
    signal: AbortSignal,
  ): Promise<Blob> {
    if (demoLoginEnabled() && !userId)
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
      `${base}${callPath(role, id)}/turns/${turn.number}/narration?${query}`,
      {
        credentials: 'include',
        signal,
        headers: demoLoginEnabled() ? { 'X-Dev-User': userId } : {},
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
    getViewer: async (id) => demoLoginEnabled() && !id ? null : optional(id ?? '', '/api/viewer'),
  }
  const profilesApi: DemoProfilesApi = {
    listProfiles: () => request(undefined, '/api/demo/profiles'),
  }
  const conversationsApi: ConversationsApi = {
    listForAgent: (user) => request(user, '/api/agent/conversations'),
  }
  const callApi: CallApi = {
    getNarration: (...args) => narration('agent', ...args),
    getCallForAgent: (user, id) => optional(user, callPath('agent', id)),
    saveContext: (user, id, text) => request(user, `${callPath('agent', id)}/context`, { text }, 'PUT'),
    requestReview: (user, id, findingId, reason) =>
      request(user, `${callPath('agent', id)}/review-requests`, { findingId, reason }, 'POST'),
  }
  const knowledgeApi: ApprovedKnowledgeApi = {
    listForAgent: (user) => request(user, '/api/agent/knowledge'),
    getForAgent: (user, id) => optional(user, `/api/agent/knowledge/${encodeURIComponent(id)}`),
  }
  const pilot = import.meta.env.VITE_LAYER2_TEMPLATE_PILOT === 'true'
  const teamReviewApi: TeamReviewApi = {
    getNarration: (...args) => narration('manager', ...args),
    listForManager: (user) => request(user, '/api/manager/conversations'),
    getCallForManager: (user, id) => optional(user, callPath('manager', id)),
    startAnalysis: !simulation && pilot
      ? (user, id) => request(user, `${callPath('manager', id)}/analysis`, undefined, 'POST')
      : undefined,
    saveDecision: (user, id, findingId, decision) =>
      request(user, `${callPath('manager', id)}/findings/${encodeURIComponent(findingId)}/decision`, decision, 'POST'),
  }
  const knowledgeReviewApi: KnowledgeReviewApi = {
    generateDrafts: pilot ? (user) => request(user, '/api/manager/knowledge/imports', undefined, 'POST') : undefined,
    editDraft: (user, id, content) => request(user, `${draftPath(id)}/content`, content, 'PUT'),
    attachVerification: (user, id, reference) => request(user, `${draftPath(id)}/verification`, reference, 'PUT'),
    listForManager: (user) => request(user, '/api/manager/knowledge/drafts'),
    getForManager: (user, id) => optional(user, draftPath(id)),
    approve: (user, id, verifiedReferenceUrl, version, authoredPolicyVersion) =>
      request(user, `${draftPath(id)}/approve`, { verifiedReferenceUrl, version, authoredPolicyVersion }, 'POST'),
    reject: (user, id, reason, version) => request(user, `${draftPath(id)}/reject`, { reason, version }, 'POST'),
    unapprove: (user, id, version) => request(user, `${draftPath(id)}/unapprove`, { version }, 'POST'),
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
