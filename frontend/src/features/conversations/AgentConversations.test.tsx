import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router'
import { AgentConversations } from './AgentConversations'
import type { Conversation, ConversationsApi } from './conversations'
import type { Viewer } from '../../types/viewer'

afterEach(cleanup)

const viewer = {
  id: 'agent-alex-morgan',
  displayName: 'Alex Morgan',
  role: 'agent',
} as const

function conversation(
  id: string,
  overrides: Partial<Conversation> = {},
): Conversation {
  return {
    id,
    topic: 'Refund',
    agentId: viewer.id,
    agentName: viewer.displayName,
    date: '2026-10-08',
    automatedResult: 'needs-review',
    reviewStatus: 'feedback-ready',
    ...overrides,
  }
}

const records = [
  conversation('C1', { reviewStatus: 'review-complete' }),
  conversation('C2', { topic: 'Delivery', reviewStatus: 'review-complete' }),
  conversation('C3'),
  conversation('C4', { topic: 'Cancellation', reviewStatus: 'review-requested' }),
  conversation('C5', {
    topic: 'Delivery',
    automatedResult: 'processing',
    reviewStatus: null,
  }),
  conversation('PRIVATE', { agentId: 'another-agent' }),
]

function mount(
  api: ConversationsApi | null = { listForAgent: async () => records },
  path = '/agent/conversations',
) {
  const router = createMemoryRouter(
    [
      {
        path: '/agent/conversations',
        element: <AgentConversations viewer={viewer} api={api} />,
      },
    ],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
  return router
}

async function open(path = '/agent/conversations') {
  const router = mount(undefined, path)
  const bar = await screen.findByRole('group', {
    name: 'Filter conversations by status',
  })
  const status = screen.getByRole<HTMLSelectElement>('combobox', {
    name: 'Review status',
  })
  return { router, bar, status }
}

function calls() {
  return within(screen.getByRole('table'))
    .queryAllByRole('link')
    .map((link) => link.textContent)
}

function deferredRecords() {
  let resolve!: (records: Conversation[]) => void
  let reject!: (error: Error) => void
  const promise = new Promise<Conversation[]>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function subject(api: ConversationsApi, identity: Viewer) {
  return (
    <MemoryRouter>
      <AgentConversations viewer={identity} api={api} />
    </MemoryRouter>
  )
}

describe('conversation loading and ownership', () => {
  it('shows only owned conversations, newest first, with separate audit and review labels', async () => {
    const listForAgent = vi.fn(async () => [
      conversation('OLD', { date: '2026-10-01' }),
      conversation('PRIVATE', { agentId: 'another-agent' }),
      conversation('NEW', {
        date: '2026-10-09',
        automatedResult: 'cannot-assess',
        reviewStatus: 'review-complete',
      }),
    ])
    mount({ listForAgent })
    await screen.findByRole('table')
    expect(listForAgent).toHaveBeenCalledWith(viewer.id)
    expect(calls()).toEqual(['NEW', 'OLD'])
    const row = screen
      .getByRole('link', { name: 'Open conversation NEW: Refund' })
      .closest('tr')!
    expect(within(row).getByText('Cannot assess')).toBeTruthy()
    expect(within(row).getByText('Review complete')).toBeTruthy()
  })

  it('disables filters while loading and enables them once records arrive', async () => {
    const pending = deferredRecords()
    mount({ listForAgent: () => pending.promise })
    expect(screen.getByRole('status').textContent).toContain('Loading')
    const search = screen.getByRole<HTMLInputElement>('searchbox', {
      name: 'Search calls',
    })
    const status = screen.getByRole<HTMLSelectElement>('combobox', {
      name: 'Review status',
    })
    expect(search.disabled).toBe(true)
    expect(status.disabled).toBe(true)
    await act(async () => pending.resolve(records))
    expect(calls()).toHaveLength(5)
    expect(search.disabled).toBe(false)
    expect(status.disabled).toBe(false)
  })

  it('retries a failed request without exposing internal error details', async () => {
    const pending = deferredRecords()
    const listForAgent = vi.fn<ConversationsApi['listForAgent']>()
      .mockRejectedValueOnce(new Error('Private server details'))
      .mockReturnValueOnce(pending.promise)
    mount({ listForAgent })
    await screen.findByRole('alert')
    expect(screen.queryByText('Private server details')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByRole('status').textContent).toContain('Loading')
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
    await act(async () => pending.resolve(records))
    expect(calls()).toHaveLength(5)
    expect(listForAgent).toHaveBeenCalledTimes(2)
  })

  it('explains unavailable data without offering a retry that cannot work', () => {
    mount(null)
    expect(screen.getByRole('alert').textContent).toBe(
      'Conversation data is not connected.',
    )
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
    expect(screen.getByRole<HTMLInputElement>('searchbox').disabled).toBe(true)
  })

  it('distinguishes an empty workspace from a search with no matches', async () => {
    mount({ listForAgent: async () => [] })
    await screen.findByRole('heading', { name: 'No conversations yet' })
    expect(
      screen.queryByRole('heading', { name: 'No matching conversations' }),
    ).toBeNull()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it.each(['viewer', 'api'] as const)(
    'hides previous records immediately when the %s changes',
    async (change) => {
      const pending = deferredRecords()
      const listForAgent = vi.fn<ConversationsApi['listForAgent']>()
        .mockResolvedValueOnce(records)
        .mockReturnValueOnce(pending.promise)
      const oldApi = { listForAgent }
      const nextApi = change === 'api' ? { listForAgent } : oldApi
      const view = render(subject(oldApi, viewer))
      await screen.findByRole('table')
      const nextViewer =
        change === 'viewer' ? { ...viewer, id: 'another-agent' } : viewer
      view.rerender(subject(nextApi, nextViewer))
      expect(screen.queryByRole('table')).toBeNull()
      expect(screen.getByRole('status').textContent).toContain('Loading')
      await act(async () => pending.resolve([
        conversation('NEW', { agentId: nextViewer.id }),
      ]))
      expect(calls()).toEqual(['NEW'])
    },
  )

  it.each([
    ['viewer', 'resolve'],
    ['viewer', 'reject'],
    ['api', 'resolve'],
    ['api', 'reject'],
  ] as const)('ignores a stale %s request that later %ss', async (change, outcome) => {
    const previous = deferredRecords()
    const current = deferredRecords()
    const listForAgent = vi.fn<ConversationsApi['listForAgent']>()
      .mockReturnValueOnce(previous.promise)
      .mockReturnValueOnce(current.promise)
    const oldApi = { listForAgent }
    const newApi = change === 'api' ? { listForAgent } : oldApi
    const nextViewer =
      change === 'viewer' ? { ...viewer, id: 'another-agent' } : viewer
    const view = render(subject(oldApi, viewer))
    view.rerender(subject(newApi, nextViewer))
    await act(async () => current.resolve([
      conversation('CURRENT', { agentId: nextViewer.id }),
    ]))
    expect(calls()).toEqual(['CURRENT'])
    await act(async () => {
      if (outcome === 'resolve') previous.resolve(records)
      else previous.reject(new Error('Stale failure'))
    })
    expect(calls()).toEqual(['CURRENT'])
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('summary status filters', () => {
  it.each([
    ['Review complete: 2', ['C1', 'C2']],
    ['Feedback ready: 1', ['C3']],
    ['Review requested: 1', ['C4']],
    ['Processing: 1', ['C5']],
  ] as const)(
    'previews %s without saving it or exposing other agents',
    async (label, expected) => {
      const { bar, router, status } = await open()
      expect(calls()).toEqual(['C1', 'C2', 'C3', 'C4', 'C5'])
      fireEvent.mouseEnter(within(bar).getByRole('button', { name: label }))
      expect(calls()).toEqual(expected)
      expect(status.value).toBe('all')
      expect(router.state.location.search).toBe('')
      fireEvent.mouseLeave(bar)
      expect(calls()).toEqual(['C1', 'C2', 'C3', 'C4', 'C5'])
    },
  )

  it('locks a clicked filter and restores it after previewing another status', async () => {
    const { bar, router, status } = await open()
    const ready = within(bar).getByRole('button', { name: 'Feedback ready: 1' })
    fireEvent.mouseEnter(ready)
    fireEvent.click(ready)
    fireEvent.mouseLeave(bar)
    expect(status.value).toBe('feedback-ready')
    expect(router.state.location.search).toBe('?status=feedback-ready')
    expect(ready.getAttribute('aria-pressed')).toBe('true')
    expect(calls()).toEqual(['C3'])
    fireEvent.mouseEnter(within(bar).getByRole('button', { name: 'Processing: 1' }))
    expect(calls()).toEqual(['C5'])
    expect(status.value).toBe('feedback-ready')
    fireEvent.mouseLeave(bar)
    expect(calls()).toEqual(['C3'])
  })

  it('combines previews with search and respects dropdown changes and Clear filters', async () => {
    const { bar, router, status } = await open('/agent/conversations?q=Refund&status=feedback-ready')
    fireEvent.mouseEnter(within(bar).getByRole('button', { name: 'Review complete: 2' }))
    expect(calls()).toEqual(['C1'])
    expect(router.state.location.search).toBe('?q=Refund&status=feedback-ready')
    fireEvent.change(status, { target: { value: 'processing' } })
    expect(calls()).toEqual([])
    expect(screen.getByRole('heading', { name: 'No matching conversations' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    fireEvent.mouseLeave(bar)
    expect(status.value).toBe('all')
    expect(router.state.location.search).toBe('')
    expect(calls()).toHaveLength(5)
  })

  it('keeps committed filters in Back/Forward history without recording hover previews', async () => {
    const { bar, router, status } = await open()
    fireEvent.click(within(bar).getByRole('button', { name: 'Feedback ready: 1' }))
    fireEvent.mouseEnter(within(bar).getByRole('button', { name: 'Review complete: 2' }))
    fireEvent.mouseLeave(bar)
    fireEvent.click(within(bar).getByRole('button', { name: 'Processing: 1' }))
    await act(() => router.navigate(-1))
    expect(status.value).toBe('feedback-ready')
    expect(calls()).toEqual(['C3'])
    await act(() => router.navigate(-1))
    expect(status.value).toBe('all')
    expect(calls()).toHaveLength(5)
    await act(() => router.navigate(1))
    expect(status.value).toBe('feedback-ready')
    expect(calls()).toEqual(['C3'])
  })
})
