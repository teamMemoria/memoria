import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { AgentConversations } from './AgentConversations'
import type { Conversation } from './conversations'

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

async function open(path = '/agent/conversations') {
  const router = createMemoryRouter(
    [
      {
        path: '/agent/conversations',
        element: (
          <AgentConversations
            viewer={viewer}
            api={{ listForAgent: async () => records }}
          />
        ),
      },
    ],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
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
