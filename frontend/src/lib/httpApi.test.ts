/// <reference types="node" />
import { webcrypto, createHash } from 'node:crypto'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createHttpApis } from './httpApi'
import { callFixture } from './callReview.test-data'
import { createDependencies } from '../app/dependencies'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('HTTP dependency boundary', () => {
  it('uses configured HTTP APIs without falling back to demo records', async () => {
    vi.stubEnv('VITE_API_BASE_URL', '/backend/')
    vi.stubEnv('VITE_DEV_USER', 'test-agent')
    const fetch = vi.fn(async () => new Response(JSON.stringify([])))
    vi.stubGlobal('fetch', fetch)
    const deps = createDependencies()
    expect(
      await deps.conversationsApi!.listForAgent('selected-agent'),
    ).toEqual([])
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/backend/api/agent/conversations')
    expect(init.credentials).toBe('include')
    expect(init.headers).toEqual({ 'X-Dev-User': 'selected-agent' })
    expect(init.signal).toBeInstanceOf(AbortSignal)
    expect(deps.knowledgeReviewApi).toBeTruthy()
  })

  it('binds knowledge decisions to the displayed version and stored reference', async () => {
    const fetch = vi.fn(async () => new Response('{}'))
    vi.stubGlobal('fetch', fetch)
    const api = createHttpApis('/').knowledgeReviewApi
    await api.approve(
      'manager',
      'draft/1',
      'https://example.test/policy',
      'sha256:reviewed',
    )
    await api.reject('manager', 'draft/2', 'Missing evidence', 'sha256:other')
    const calls = fetch.mock.calls as unknown as [string, RequestInit][]
    expect(calls[0][0]).toBe('/api/manager/knowledge/drafts/draft%2F1/approve')
    expect(calls[0][1].headers).toMatchObject({ 'X-Dev-User': 'manager' })
    expect(calls[1][1].headers).toMatchObject({ 'X-Dev-User': 'manager' })
    expect(JSON.parse(calls[0][1].body as string)).toEqual({
      verifiedReferenceUrl: 'https://example.test/policy',
      version: 'sha256:reviewed',
    })
    expect(JSON.parse(calls[1][1].body as string)).toEqual({
      reason: 'Missing evidence',
      version: 'sha256:other',
    })
  })

  it('never ships a development identity header in production', async () => {
    vi.stubEnv('DEV', false)
    const fetch = vi.fn(async () => new Response('{}'))
    vi.stubGlobal('fetch', fetch)
    await createHttpApis('/').viewerApi.getViewer('test-agent')
    expect(
      (fetch.mock.calls[0] as unknown as [string, RequestInit])[1].headers,
    ).toEqual({})
  })

  it('encodes path identifiers and sends only the existing write contracts', async () => {
    const fetch = vi.fn(async () => new Response('{}'))
    vi.stubGlobal('fetch', fetch)
    const apis = createHttpApis('/')
    await apis.callApi.saveContext('agent', 'call /1', 'Observed context')
    await apis.callApi.requestReview(
      'agent',
      'call /1',
      'finding',
      'Please check',
    )
    await apis.teamReviewApi.saveDecision('manager', 'call /1', 'f/2', {
      outcome: 'cannot-assess',
      reason: 'Record missing',
      feedback: 'No fault established',
    })
    const calls = fetch.mock.calls as unknown as [string, RequestInit][]
    expect(calls[0][0]).toBe('/api/agent/conversations/call%20%2F1/context')
    expect(calls[0][1].method).toBe('PUT')
    expect(JSON.parse(calls[0][1].body as string)).toEqual({
      text: 'Observed context',
    })
    expect(JSON.parse(calls[1][1].body as string)).toEqual({
      findingId: 'finding',
      reason: 'Please check',
    })
    expect(calls[2][0]).toBe(
      '/api/manager/conversations/call%20%2F1/findings/f%2F2/decision',
    )
    expect(calls[2][1].method).toBe('POST')
  })

  it('distinguishes absent records and identity from errors; never exposes server diagnostics', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockResolvedValueOnce(new Response('', { status: 404 }))
      .mockResolvedValueOnce(
        new Response('private SQL details', { status: 503 }),
      )
      .mockRejectedValueOnce(new DOMException('timed out', 'TimeoutError'))
    vi.stubGlobal('fetch', fetch)
    const apis = createHttpApis('/')
    expect(await apis.viewerApi.getViewer('test-agent')).toBeNull()
    expect(await apis.callApi.getCallForAgent('agent', 'absent')).toBeNull()
    await expect(apis.conversationsApi.listForAgent('agent')).rejects.toThrow(
      'The request could not be completed.',
    )
    await expect(apis.conversationsApi.listForAgent('agent')).rejects.toThrow(
      'timed out',
    )
  })
})

function mockResponse(value: unknown, status = 200) {
  const fetch = vi.fn<typeof globalThis.fetch>(async () => new Response(JSON.stringify(value), { status }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

describe('database profile HTTP integration', () => {
  it('selects HTTP for every workspace API and never falls back to fixtures', async () => {
    vi.stubEnv('VITE_DEMO_BACKEND', 'true')
    vi.stubEnv('VITE_API_BASE_URL', '/backend/')
    const fetch = mockResponse([])
    const apis = createDependencies()
    await apis.conversationsApi!.listForAgent('chosen-agent')
    await apis.knowledgeApi!.listForAgent('chosen-agent')
    await apis.teamReviewApi!.listForManager('chosen-manager')
    await apis.knowledgeReviewApi!.listForManager('chosen-manager')
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      '/backend/api/agent/conversations', '/backend/api/agent/knowledge',
      '/backend/api/manager/conversations', '/backend/api/manager/knowledge/drafts',
    ])
    expect(fetch.mock.calls.map(([, init]) => init?.headers)).toEqual([
      { 'X-Dev-User': 'chosen-agent' }, { 'X-Dev-User': 'chosen-agent' },
      { 'X-Dev-User': 'chosen-manager' }, { 'X-Dev-User': 'chosen-manager' },
    ])
    expect(fetch.mock.calls[0][1]?.credentials).toBe('include')
    expect(fetch.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal)
  })

  it('binds every request to its supplied viewer, even when storage is unavailable or a different profile is selected', async () => {
    vi.stubGlobal('localStorage', { getItem() { throw new Error('blocked') } })
    const fetch = mockResponse([])
    const apis = createHttpApis()
    await Promise.all([
      apis.conversationsApi.listForAgent('first-agent'),
      apis.conversationsApi.listForAgent('second-agent'),
      apis.conversationsApi.listForAgent('first-agent'),
    ])
    expect(fetch.mock.calls.map(([, init]) => init?.headers)).toEqual([
      { 'X-Dev-User': 'first-agent' }, { 'X-Dev-User': 'second-agent' }, { 'X-Dev-User': 'first-agent' },
    ])
  })

  it('sends no default identity before a profile is chosen', async () => {
    const fetch = mockResponse([])
    const apis = createHttpApis()
    expect(await apis.viewerApi.getViewer()).toBeNull()
    await expect(apis.conversationsApi.listForAgent('')).rejects.toThrow('Choose a profile')
    expect(fetch).not.toHaveBeenCalled()
    await apis.profilesApi.listProfiles()
    expect(fetch.mock.calls[0][1]?.headers).toEqual({})
  })

  it('preserves server-owned profile names, IDs, scores and exact evidence', async () => {
    const call = await callFixture({ agentId: 'demo-abcd-alex', agentName: 'Alex (demo)' })
    const fetch = mockResponse(call)
    const actual = await createHttpApis().callApi.getCallForAgent('demo-abcd-alex', call.id)
    expect(actual).toEqual(call)
    expect(fetch.mock.calls[0][1]?.headers).toEqual({ 'X-Dev-User': 'demo-abcd-alex' })
    mockResponse({ ...call, agentId: 'unrelated-user' })
    expect((await createHttpApis().callApi.getCallForAgent('unrelated-user', call.id))?.agentName).toBe('Alex (demo)')
  })

  it('uses the selected profile for viewer lookup and preserves database conversation counts', async () => {
    const profile = { id: 'demo-abcd-alex', displayName: 'Alex', role: 'agent', conversationCount: 2 }
    mockResponse([profile])
    expect(await createHttpApis().profilesApi.listProfiles()).toEqual([profile])
    const fetch = mockResponse(profile)
    expect(await createHttpApis().viewerApi.getViewer(profile.id)).toEqual(profile)
    expect(fetch.mock.calls[0][1]?.headers).toEqual({ 'X-Dev-User': profile.id })
  })

  it('never ships development identity headers in production', async () => {
    vi.stubEnv('DEV', false)
    const fetch = mockResponse([])
    await createHttpApis().conversationsApi.listForAgent('selected-agent')
    expect(fetch.mock.calls[0][1]?.headers).toEqual({})
  })

  it('keeps ownership and missing records distinct from server or network failures', async () => {
    mockResponse({}, 404)
    expect(await createHttpApis().callApi.getCallForAgent('agent', 'someone-elses-call')).toBeNull()
    mockResponse({}, 401)
    expect(await createHttpApis().viewerApi.getViewer('deleted-profile')).toBeNull()
    mockResponse('private SQL details', 503)
    await expect(createHttpApis().conversationsApi.listForAgent('agent')).rejects.toThrow('The request could not be completed.')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(createHttpApis().conversationsApi.listForAgent('agent')).rejects.toThrow('Failed to fetch')
  })

  it('encodes call IDs and sends existing write contracts with the correct actor', async () => {
    const fetch = mockResponse({})
    const apis = createHttpApis()
    await apis.callApi.saveContext('agent-a', 'call /1', 'Context')
    await apis.callApi.requestReview('agent-a', 'call /1', 'finding', 'Check this')
    await apis.teamReviewApi.saveDecision('manager-a', 'call /1', 'f/2', { outcome: 'cannot-assess', reason: 'Unknown', feedback: 'Record missing' })
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      '/api/agent/conversations/call%20%2F1/context',
      '/api/agent/conversations/call%20%2F1/review-requests',
      '/api/manager/conversations/call%20%2F1/findings/f%2F2/decision',
    ])
    expect(fetch.mock.calls[0][1]?.method).toBe('PUT')
    expect(JSON.parse(fetch.mock.calls[0][1]?.body as string)).toEqual({ text: 'Context' })
    expect(fetch.mock.calls[2][1]?.headers).toEqual({ 'Content-Type': 'application/json', 'X-Dev-User': 'manager-a' })
  })

})


describe('private generated narration', () => {
  const turn = { number: 7, speaker: 'Agent' as const, text: 'Café — [PERSON_1]', time: null }
  it.each(['agent', 'manager'] as const)('binds %s audio to exact text and the current viewer', async role => {
    vi.stubGlobal('crypto', webcrypto)
    const fetch = vi.fn(async () => new Response('audio bytes', { headers: { 'Content-Type': 'audio/mpeg' } }))
    vi.stubGlobal('fetch', fetch)
    const apis = createHttpApis('/backend')
    const api = role === 'agent' ? apis.callApi : apis.teamReviewApi
    const controller = new AbortController()
    const audio = await api.getNarration!('viewer-1', 'call/1', turn, 'am_michael', controller.signal)
    expect(audio.type).toBe('audio/mpeg')
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain(`/api/${role}/conversations/call%2F1/turns/7/narration`)
    expect(url).toContain(createHash('sha256').update(turn.text).digest('hex'))
    expect(url).not.toContain(turn.text)
    expect(init.headers).toEqual({ 'X-Dev-User': 'viewer-1' })
    expect(init.signal).toBe(controller.signal)
    expect(init.credentials).toBe('include')
  })
  it.each([409, 503, 404, 500])('fails closed for status %s', async status => {
    vi.stubGlobal('crypto', webcrypto)
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status })))
    await expect(createHttpApis().callApi.getNarration!('viewer', '1', turn, 'am_michael', new AbortController().signal)).rejects.toThrow()
  })
  it('does not send development identity headers for production audio', async () => {
    vi.stubGlobal('crypto', webcrypto)
    vi.stubEnv('DEV', false)
    const fetch = vi.fn(async () => new Response('audio', { headers: { 'Content-Type': 'audio/mpeg' } }))
    vi.stubGlobal('fetch', fetch)
    await createHttpApis().callApi.getNarration!('viewer', '1', turn, 'am_michael', new AbortController().signal)
    expect((fetch.mock.calls[0] as unknown as [string, RequestInit])[1].headers).toEqual({})
  })
})
