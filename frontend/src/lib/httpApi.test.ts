import { afterEach, describe, expect, it, vi } from 'vitest'
import { createHttpApis } from './httpApi'
import { createDependencies } from '../app/dependencies'
import { callFixture } from './callReview.test-data'

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })

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

  it('removes only legacy profile suffixes, preserving IDs, stored scores and exact evidence', async () => {
    const call = await callFixture({ agentId: 'demo-abcd-alex', agentName: 'Alex (demo)' })
    const fetch = mockResponse(call)
    const actual = await createHttpApis().callApi.getCallForAgent('demo-abcd-alex', call.id)
    expect(actual).toEqual({ ...call, agentName: 'Alex' })
    expect(fetch.mock.calls[0][1]?.headers).toEqual({ 'X-Dev-User': 'demo-abcd-alex' })
    mockResponse({ ...call, agentId: 'unrelated-user' })
    expect((await createHttpApis().callApi.getCallForAgent('unrelated-user', call.id))?.agentName).toBe('Alex (demo)')
  })

  it('uses the selected profile for viewer lookup and preserves database conversation counts', async () => {
    const profile = { id: 'demo-abcd-alex', displayName: 'Alex (demo)', role: 'agent', conversationCount: 2 }
    mockResponse([profile])
    expect(await createHttpApis().profilesApi.listProfiles()).toEqual([{ ...profile, displayName: 'Alex' }])
    const fetch = mockResponse(profile)
    expect(await createHttpApis().viewerApi.getViewer(profile.id)).toEqual({ ...profile, displayName: 'Alex' })
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

  it('keeps knowledge read-only without calling nonexistent decision endpoints', async () => {
    const fetch = mockResponse({})
    const api = createHttpApis().knowledgeReviewApi
    expect(api.decisionsAvailable).toBe(false)
    await expect(api.approve('manager', 'draft/1', 'https://example.test/policy')).rejects.toThrow('not available')
    await expect(api.reject('manager', 'draft/2', 'Missing evidence')).rejects.toThrow('not available')
    expect(fetch).not.toHaveBeenCalled()
  })
})
