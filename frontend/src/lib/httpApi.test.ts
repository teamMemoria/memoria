/// <reference types="node" />
import { createHash, webcrypto } from 'node:crypto'
import { afterEach, expect, it, vi } from 'vitest'
import { createDependencies } from '../app/dependencies'
import { callFixture } from '../test/callReview.test-data'
import { createHttpApis } from './httpApi'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

function mockFetch(response: () => Response = () => Response.json({})) {
  const fetch = vi.fn<typeof globalThis.fetch>(async () => response())
  vi.stubGlobal('fetch', fetch)
  return fetch
}

it('uses the configured backend for both roles and keeps request credentials', async () => {
  vi.stubEnv('VITE_API_BASE_URL', '/backend/')
  const fetch = mockFetch(() => Response.json([]))
  const api = createDependencies()
  expect(await api.conversationsApi!.listForAgent('agent')).toEqual([])
  await api.knowledgeApi!.listForAgent('agent')
  await api.teamReviewApi!.listForManager('manager')
  await api.knowledgeReviewApi!.listForManager('manager')
  expect(fetch.mock.calls.map(([url, init]) => [url, init?.headers])).toEqual([
    ['/backend/api/agent/conversations', { 'X-Dev-User': 'agent' }],
    ['/backend/api/agent/knowledge', { 'X-Dev-User': 'agent' }],
    ['/backend/api/manager/conversations', { 'X-Dev-User': 'manager' }],
    ['/backend/api/manager/knowledge/drafts', { 'X-Dev-User': 'manager' }],
  ])
  expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: 'include', signal: expect.any(AbortSignal) })
})

it('uses the local profile API in development and supplies no default identity', async () => {
  vi.stubEnv('MODE', 'development')
  vi.stubEnv('DEV', true)
  const profiles = [{ id: 'abc', displayName: 'Alex', role: 'agent', conversationCount: 2 }]
  const fetch = mockFetch(() => Response.json(profiles))
  const api = createDependencies()
  expect(await api.viewerApi!.getViewer()).toBeNull()
  await expect(api.conversationsApi!.listForAgent('')).rejects.toThrow('Choose a profile')
  expect(fetch).not.toHaveBeenCalled()
  expect(await api.profilesApi!.listProfiles()).toEqual(profiles)
  expect(fetch.mock.calls[0]).toEqual(['/api/demo/profiles', expect.objectContaining({ headers: {} })])
})

it.each([undefined, 'false', '1', 'true'])('enables production demo login only for true (%s)', async (value) => {
  vi.stubEnv('DEV', false)
  vi.stubEnv('VITE_DEMO_LOGIN', value)
  vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test')
  const fetch = mockFetch()
  const api = createDependencies()
  expect(Boolean(api.profilesApi)).toBe(value === 'true')
  await api.viewerApi!.getViewer('profile')
  expect(String(fetch.mock.calls[0][0])).toMatch(/^https:\/\/api\.example\.test\//)
  expect(fetch.mock.calls[0][1]?.headers).toEqual(value === 'true' ? { 'X-Dev-User': 'profile' } : {})
})

it('uses the actor supplied to each request when storage is unavailable', async () => {
  vi.stubGlobal('localStorage', { getItem() { throw new Error('blocked') } })
  const fetch = mockFetch(() => Response.json([]))
  await Promise.all(['first', 'second', 'first'].map(createHttpApis().conversationsApi.listForAgent))
  expect(fetch.mock.calls.map(([, init]) => init?.headers)).toEqual(
    ['first', 'second', 'first'].map((id) => ({ 'X-Dev-User': id })),
  )
})

it('keeps exact call data and suppresses server diagnostics', async () => {
  const call = await callFixture({ agentId: 'abc', agentName: 'Alex (demo)' })
  const fetch = mockFetch(() => Response.json(call))
  const api = createHttpApis()
  expect(await api.callApi.getCallForAgent('abc', call.id)).toEqual(call)
  expect(fetch.mock.calls[0][1]?.headers).toEqual({ 'X-Dev-User': 'abc' })
  fetch.mockResolvedValueOnce(new Response(null, { status: 404 }))
  expect(await api.callApi.getCallForAgent('abc', 'absent')).toBeNull()
  fetch.mockResolvedValueOnce(new Response(null, { status: 401 }))
  expect(await api.viewerApi.getViewer('deleted-profile')).toBeNull()
  fetch.mockResolvedValueOnce(new Response('private SQL details', { status: 503 }))
  await expect(api.conversationsApi.listForAgent('abc')).rejects.toThrow('The request could not be completed.')
  fetch.mockRejectedValueOnce(new DOMException('timed out', 'TimeoutError'))
  await expect(api.conversationsApi.listForAgent('abc')).rejects.toThrow('timed out')
})

it('encodes call IDs and sends context and decisions with the correct actor', async () => {
  const fetch = mockFetch()
  const { callApi, teamReviewApi } = createHttpApis()
  const decision = { outcome: 'cannot-assess', reason: 'Unknown', feedback: 'Record missing' } as const
  await callApi.saveContext('agent', 'call /1', 'Context')
  await callApi.requestReview('agent', 'call /1', 'finding', 'Check this')
  await teamReviewApi.saveDecision('manager', 'call /1', 'f/2', decision)
  expect(fetch.mock.calls.map(([url, init]) => [url, init?.method, init?.headers, JSON.parse(String(init?.body))])).toEqual([
    ['/api/agent/conversations/call%20%2F1/context', 'PUT', headers('agent'), { text: 'Context' }],
    ['/api/agent/conversations/call%20%2F1/review-requests', 'POST', headers('agent'), { findingId: 'finding', reason: 'Check this' }],
    ['/api/manager/conversations/call%20%2F1/findings/f%2F2/decision', 'POST', headers('manager'), decision],
  ])
})

function headers(id: string) {
  return { 'Content-Type': 'application/json', 'X-Dev-User': id }
}

it('binds knowledge changes to the reviewed version and reference', async () => {
  const fetch = mockFetch()
  const api = createHttpApis().knowledgeReviewApi
  const version = 'sha256:reviewed'
  const verifiedReferenceUrl = 'https://example.test/policy'
  const content = { title: 'Refund policy', question: 'What should the Agent check?', guidance: 'Check the policy.', version }
  await api.editDraft!('manager', 'draft/1', content)
  await api.approve('manager', 'draft/1', verifiedReferenceUrl, version)
  await api.reject('manager', 'draft/1', 'Missing evidence', version)
  await api.unapprove('manager', 'draft/1', version)
  const prefix = '/api/manager/knowledge/drafts/draft%2F1/'
  expect(fetch.mock.calls.map(([url, init]) => [url, init?.method, init?.headers, JSON.parse(String(init?.body))])).toEqual([
    [prefix + 'content', 'PUT', headers('manager'), content],
    [prefix + 'approve', 'POST', headers('manager'), { verifiedReferenceUrl, version }],
    [prefix + 'reject', 'POST', headers('manager'), { reason: 'Missing evidence', version }],
    [prefix + 'unapprove', 'POST', headers('manager'), { version }],
  ])
})

const turn = { number: 7, speaker: 'Agent' as const, text: 'Café — [PERSON_1]', time: null }
it.each(['agent', 'manager', 'production'] as const)('binds %s narration to the displayed text and viewer', async (role) => {
  vi.stubGlobal('crypto', webcrypto)
  if (role === 'production') vi.stubEnv('DEV', false)
  const fetch = mockFetch(() => new Response('audio', { headers: { 'Content-Type': 'audio/mpeg' } }))
  const { callApi, teamReviewApi } = createHttpApis('/backend')
  const api = role === 'manager' ? teamReviewApi : callApi
  const { signal } = new AbortController()
  const audio = await api.getNarration!('viewer', 'call/1', turn, 'am_michael', signal)
  const [url, init] = fetch.mock.calls[0]
  expect(audio.type).toBe('audio/mpeg')
  expect(url).toContain(`/api/${role === 'manager' ? role : 'agent'}/conversations/call%2F1/turns/7/narration`)
  expect(url).toContain(createHash('sha256').update(turn.text).digest('hex'))
  expect(url).not.toContain(turn.text)
  expect(init).toMatchObject({ signal, credentials: 'include', headers: role === 'production' ? {} : { 'X-Dev-User': 'viewer' } })
})

it.each([409, 503, 404, 500])('fails closed for narration status %s', async (status) => {
  vi.stubGlobal('crypto', webcrypto)
  mockFetch(() => new Response('{}', { status }))
  await expect(createHttpApis().callApi.getNarration!('viewer', '1', turn, 'am_michael', new AbortController().signal)).rejects.toThrow()
})
