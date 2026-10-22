import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router'
import type { CallApi, CallReview } from '../types/callReview'
import type { Viewer } from '../types/viewer'
import type { Conversation } from '../features/conversations/conversations'
import { agent, callFixture } from '../lib/callReview.test-data'
import { createDependencies } from './dependencies'
import App from './App'

afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
})

function open(
  call: CallReview,
  path: string,
  viewer: Viewer = agent,
  api: CallApi = { getCallForAgent: async () => call },
) {
  const record: Conversation = {
    id: call.id,
    topic: call.topic,
    agentId: call.agentId,
    agentName: call.agentName,
    date: call.date,
    automatedResult: 'needs-review',
    reviewStatus: 'feedback-ready',
  }
  const router = createMemoryRouter([
    {
      path: '*',
      element: (
        <App
          viewerApi={{ getViewer: async () => viewer }}
          conversationsApi={{ listForAgent: async () => [record] }}
          callApi={api}
        />
      ),
    },
  ], { initialEntries: [path] })
  render(<RouterProvider router={router} />)
  return router
}

describe('call overview routing', () => {
  it('connects the real list and overview while preserving filters through return and Back/Forward', async () => {
    const call = await callFixture()
    const getCallForAgent = vi.fn(async () => call)
    const search = '?q=Refund&status=feedback-ready'
    const router = open(call, `/agent/conversations${search}`, agent, { getCallForAgent })
    fireEvent.click(await screen.findByRole('link', {
      name: `Open conversation ${call.id}: ${call.topic}`,
    }))
    await screen.findByRole('heading', { name: call.topic })
    expect(getCallForAgent).toHaveBeenCalledWith(agent.id, call.id)
    expect(router.state.location.pathname).toBe(`/agent/conversations/${call.id}`)
    expect(router.state.location.search).toBe(search)
    await act(() => router.navigate(-1))
    await screen.findByRole('table')
    expect(screen.getByRole<HTMLInputElement>('searchbox', { name: 'Search calls' }).value)
      .toBe('Refund')
    expect(screen.getByRole<HTMLSelectElement>('combobox', { name: 'Review status' }).value)
      .toBe('feedback-ready')
    await act(() => router.navigate(1))
    await screen.findByRole('heading', { name: call.topic })
    const main = within(screen.getByRole('main'))
    fireEvent.click(main.getByRole('link', { name: 'Conversations' }))
    await screen.findByRole('table')
    expect(router.state.location.pathname).toBe('/agent/conversations')
    expect(router.state.location.search).toBe(search)
    expect(screen.getByRole('link', {
      name: `Open conversation ${call.id}: ${call.topic}`,
    })).toBeTruthy()
  })

  it('opens a directly linked call without hardcoding C1042', async () => {
    const call = await callFixture({
      id: 'C2050', topic: 'Delivery question', summary: 'A different call summary.',
    })
    const getCallForAgent = vi.fn(async () => call)
    open(call, '/agent/conversations/C2050', agent, { getCallForAgent })
    await screen.findByRole('heading', { name: 'Delivery question' })
    expect(getCallForAgent).toHaveBeenCalledWith(agent.id, 'C2050')
    expect(screen.getByText('A different call summary.')).toBeTruthy()
    expect(screen.getByRole('list', { name: 'Call details' }).textContent).toContain('Call C2050')
  })

  it('blocks a Manager from opening the Agent call route without fetching it', async () => {
    const call = await callFixture()
    const getCallForAgent = vi.fn<CallApi['getCallForAgent']>()
    open(call, '/agent/conversations/C1042', {
      id: 'manager-maya-chen', displayName: 'Maya Chen', role: 'manager',
    }, { getCallForAgent })
    await screen.findByRole('heading', { name: 'Page unavailable for your role' })
    expect(getCallForAgent).not.toHaveBeenCalled()
    expect(screen.queryByRole('region', { name: 'Automatic feedback' })).toBeNull()
  })

  it('does not expose another Agent’s call returned for a direct link', async () => {
    const call = await callFixture({ agentId: 'another-agent' })
    open(call, '/agent/conversations/C1042')
    await screen.findByRole('heading', { name: 'Conversation unavailable' })
    expect(screen.queryByText(call.summary)).toBeNull()
    expect(screen.queryByRole('region', { name: 'Automatic feedback' })).toBeNull()
  })

  it('does not supply development call data in production', () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_DEV_ROLE', 'agent')
    expect(createDependencies()).toMatchObject({
      viewerApi: null, conversationsApi: null, callApi: null,
    })
  })
})
