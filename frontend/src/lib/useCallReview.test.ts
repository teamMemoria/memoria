import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CallApi, CallReview } from '../types/callReview'
import { agent, callFixture, deferred } from './callReview.test-data'
import { useCallReview } from './useCallReview'

afterEach(cleanup)

type Request = {
  api: CallApi | null
  agentId: string
  conversationId: string
}

function open(request: Request) {
  return renderHook(
    ({ api, agentId, conversationId }) =>
      useCallReview(api, agentId, conversationId),
    { initialProps: request },
  )
}

describe('call loading', () => {
  it('loads the requested call for the current agent', async () => {
    const call = await callFixture()
    const pending = deferred<CallReview | null>()
    const getCallForAgent = vi.fn(() => pending.promise)
    const { result } = open({
      api: { getCallForAgent },
      agentId: agent.id,
      conversationId: call.id,
    })
    expect(result.current.status).toBe('loading')
    expect(getCallForAgent).toHaveBeenCalledWith(agent.id, call.id)
    await act(async () => pending.resolve(call))
    expect(result.current).toMatchObject({ status: 'ready', call })
  })

  it('reports an unavailable data source without requesting a call', () => {
    const { result } = open({
      api: null,
      agentId: agent.id,
      conversationId: 'C1042',
    })
    expect(result.current.status).toBe('unavailable')
    expect(result.current).not.toHaveProperty('call')
  })

  it.each(['missing', 'wrong owner', 'wrong ID'])(
    'rejects a response with a %s call',
    async (reason) => {
      const call = await callFixture()
      const response = reason === 'missing'
        ? null
        : {
            ...call,
            ...(reason === 'wrong owner'
              ? { agentId: 'another-agent' }
              : { id: 'another-call' }),
          }
      const { result } = open({
        api: { getCallForAgent: async () => response },
        agentId: agent.id,
        conversationId: call.id,
      })
      await waitFor(() => expect(result.current.status).toBe('unavailable'))
      expect(result.current).not.toHaveProperty('call')
    },
  )

  it('retries a failed request and shows loading until the retry completes', async () => {
    const call = await callFixture()
    const pending = deferred<CallReview | null>()
    const getCallForAgent = vi.fn<CallApi['getCallForAgent']>()
      .mockRejectedValueOnce(new Error('Private server details'))
      .mockReturnValueOnce(pending.promise)
    const { result } = open({
      api: { getCallForAgent },
      agentId: agent.id,
      conversationId: call.id,
    })
    await waitFor(() => expect(result.current.status).toBe('error'))
    act(() => result.current.retry())
    expect(result.current.status).toBe('loading')
    expect(result.current).not.toHaveProperty('call')
    await act(async () => pending.resolve(call))
    expect(result.current).toMatchObject({ status: 'ready', call })
    expect(getCallForAgent).toHaveBeenCalledTimes(2)
  })
})

describe('request changes and stale responses', () => {
  it.each(['api', 'agent', 'conversation'] as const)(
    'waits for a fresh response when the %s changes back during loading',
    async (change) => {
      const call = await callFixture()
      const intermediate = deferred<CallReview | null>()
      const current = deferred<CallReview | null>()
      const getCallForAgent = vi.fn<CallApi['getCallForAgent']>()
        .mockResolvedValueOnce(call)
        .mockReturnValueOnce(intermediate.promise)
        .mockReturnValueOnce(current.promise)
      const request: Request = {
        api: { getCallForAgent },
        agentId: agent.id,
        conversationId: call.id,
      }
      const next = {
        ...request,
        ...(change === 'api' ? { api: { getCallForAgent } } : {}),
        ...(change === 'agent' ? { agentId: 'another-agent' } : {}),
        ...(change === 'conversation' ? { conversationId: 'C1050' } : {}),
      }
      const { result, rerender } = open(request)
      await waitFor(() => expect(result.current.status).toBe('ready'))
      rerender(next)
      expect(result.current.status).toBe('loading')
      rerender(request)
      expect(result.current.status).toBe('loading')
      expect(result.current).not.toHaveProperty('call')
      await act(async () => intermediate.resolve(null))
      expect(result.current.status).toBe('loading')
      const updated = { ...call, summary: 'The updated call summary.' }
      await act(async () => current.resolve(updated))
      expect(result.current).toMatchObject({ status: 'ready', call: updated })
    },
  )

  it('waits for a fresh response after the same API reconnects', async () => {
    const call = await callFixture()
    const pending = deferred<CallReview | null>()
    const getCallForAgent = vi.fn<CallApi['getCallForAgent']>()
      .mockResolvedValueOnce(call)
      .mockReturnValueOnce(pending.promise)
    const request: Request = {
      api: { getCallForAgent },
      agentId: agent.id,
      conversationId: call.id,
    }
    const { result, rerender } = open(request)
    await waitFor(() => expect(result.current.status).toBe('ready'))
    rerender({ ...request, api: null })
    expect(result.current.status).toBe('unavailable')
    expect(result.current).not.toHaveProperty('call')
    rerender(request)
    expect(result.current.status).toBe('loading')
    expect(result.current).not.toHaveProperty('call')
    await act(async () => pending.resolve(null))
    expect(result.current.status).toBe('unavailable')
  })

  it.each(['api', 'agent', 'conversation'] as const)(
    'hides previous call data immediately when the %s changes',
    async (change) => {
      const previous = await callFixture()
      const pending = deferred<CallReview | null>()
      const getCallForAgent = vi.fn<CallApi['getCallForAgent']>()
        .mockResolvedValueOnce(previous)
        .mockReturnValueOnce(pending.promise)
      const request: Request = {
        api: { getCallForAgent },
        agentId: agent.id,
        conversationId: previous.id,
      }
      const next = {
        ...request,
        ...(change === 'api' ? { api: { getCallForAgent } } : {}),
        ...(change === 'agent' ? { agentId: 'another-agent' } : {}),
        ...(change === 'conversation' ? { conversationId: 'C1050' } : {}),
      }
      const current = {
        ...previous,
        id: next.conversationId,
        agentId: next.agentId,
        summary: 'The current call summary.',
      }
      const { result, rerender } = open(request)
      await waitFor(() => expect(result.current.status).toBe('ready'))
      rerender(next)
      expect(result.current.status).toBe('loading')
      expect(result.current).not.toHaveProperty('call')
      await act(async () => pending.resolve(current))
      expect(result.current).toMatchObject({ status: 'ready', call: current })
    },
  )

  it.each([
    ['api', 'resolve'],
    ['api', 'reject'],
    ['agent', 'resolve'],
    ['agent', 'reject'],
    ['conversation', 'resolve'],
    ['conversation', 'reject'],
  ] as const)('ignores a stale %s request that later %ss', async (change, outcome) => {
    const call = await callFixture()
    const previous = deferred<CallReview | null>()
    const pending = deferred<CallReview | null>()
    const getCallForAgent = vi.fn<CallApi['getCallForAgent']>()
      .mockReturnValueOnce(previous.promise)
      .mockReturnValueOnce(pending.promise)
    const request: Request = {
      api: { getCallForAgent },
      agentId: agent.id,
      conversationId: call.id,
    }
    const next = {
      ...request,
      ...(change === 'api' ? { api: { getCallForAgent } } : {}),
      ...(change === 'agent' ? { agentId: 'another-agent' } : {}),
      ...(change === 'conversation' ? { conversationId: 'C1050' } : {}),
    }
    const current = {
      ...call,
      id: next.conversationId,
      agentId: next.agentId,
      summary: 'The current call summary.',
    }
    const { result, rerender } = open(request)
    rerender(next)
    await act(async () => pending.resolve(current))
    await act(async () => {
      if (outcome === 'resolve') previous.resolve(call)
      else previous.reject(new Error('Old request failed'))
    })
    expect(result.current).toMatchObject({ status: 'ready', call: current })
  })
})
