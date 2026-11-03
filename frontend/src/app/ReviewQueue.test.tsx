import { fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { createDevTeamReviewApi } from '../features/review-queue/devTeamReviewApi'
import type { TeamConversation } from '../features/review-queue/teamQueue'
import { agent, createDevCallApi, manager, openApp } from './TestSetup'

const path = '/manager/conversations'
const asManager = { getViewer: async () => manager }
const calls = () =>
  screen.getAllByRole<HTMLTableRowElement>('row').slice(1).map((row) => row.cells[0].textContent)
const status = () => screen.getByRole<HTMLSelectElement>('combobox', { name: 'Review status' })

describe('Manager review queue', () => {
  it('opens on flagged feedback with the agent, conversation, flag reason and status', async () => {
    openApp({ path, viewerApi: asManager })
    await screen.findByRole('table')
    expect(screen.getByText('2 flagged for review')).toBeTruthy()
    expect(status().value).toBe('review-requested')
    expect(calls()).toEqual(['C1058', 'C1051'])
    const row = screen.getByRole('link', { name: /^Review C1051/ }).closest('tr')!
    expect(within(row).getByText('Priya Shah')).toBeTruthy()
    expect(within(row).getByText('Lamp exchange')).toBeTruthy()
    expect(within(row).getByText('Stock was checked in the order system before the call.')).toBeTruthy()
    expect(within(row).getByText('Exchange offered without checking stock.')).toBeTruthy()
    expect(within(row).getByText('Review requested')).toBeTruthy()
  })

  it('filters by status and search, and clears back to flagged feedback', async () => {
    const { router } = openApp({ path, viewerApi: asManager })
    await screen.findByRole('table')
    fireEvent.change(status(), { target: { value: 'all' } })
    expect(calls()).toHaveLength(6)
    fireEvent.change(status(), { target: { value: 'review-complete' } })
    expect(calls()).toEqual(['C1060'])
    fireEvent.change(status(), { target: { value: 'processing' } })
    expect(calls()).toEqual(['C1063'])
    fireEvent.change(status(), { target: { value: 'feedback-ready' } })
    expect(calls()).toEqual(['C1047', 'C1042'])
    expect(router.state.location.search).toBe('?status=feedback-ready')
    fireEvent.change(status(), { target: { value: 'all' } })
    const search = screen.getByRole('searchbox', { name: 'Search team calls' })
    fireEvent.change(search, { target: { value: 'stock' } })
    expect(calls()).toEqual(['C1051'])
    fireEvent.change(search, { target: { value: 'no such call' } })
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(calls()).toEqual(['C1058', 'C1051'])
    expect(router.state.location.search).toBe('')
  })

  it('opens the flagged finding from its row and keeps the filters on return', async () => {
    const { router } = openApp({ path: `${path}?q=lamp`, viewerApi: asManager })
    fireEvent.click(await screen.findByRole('link', { name: 'Review C1051: Exchange offered without checking stock.' }))
    await screen.findByRole('heading', { name: 'Exchange offered without checking stock.', level: 1 })
    expect(router.state.location.pathname).toBe('/manager/conversations/C1051/findings/answer-support')
    fireEvent.click(screen.getByRole('link', { name: 'Team conversations', current: false }))
    await screen.findByRole('table')
    expect(router.state.location.search).toBe('?q=lamp')
    expect(calls()).toEqual(['C1051'])
  })

  it('shows feedback an agent flagged in this session', async () => {
    const callApi = createDevCallApi()
    await callApi.requestReview(agent.id, 'C1042', 'procedure-order', 'Purchase was verified in chat.')
    openApp({ path, viewerApi: asManager, callApi, teamReviewApi: createDevTeamReviewApi(callApi) })
    await screen.findByRole('table')
    expect(calls()).toEqual(['C1042', 'C1058', 'C1051'])
    const row = screen.getByRole('link', { name: /^Review C1042/ }).closest('tr')!
    expect(within(row).getByText('Purchase was verified in chat.')).toBeTruthy()
    expect(within(row).getByText('Refund offered before purchase verification.')).toBeTruthy()
  })

  it('shows loading, error with retry, and empty states', async () => {
    const listForManager = vi.fn()
      .mockRejectedValueOnce(new Error('Internal details'))
      .mockResolvedValueOnce([])
    openApp({ path, viewerApi: asManager, teamReviewApi: { ...createDevTeamReviewApi(), listForManager } })
    expect(await screen.findByText('Loading team conversations…')).toBeTruthy()
    expect((await screen.findByRole('alert')).textContent).toBe('Team conversations could not be loaded. Please try again.')
    expect(screen.queryByText('Internal details')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByRole('heading', { name: 'No team conversations yet' })
  })

  it('says when nothing is flagged and offers all conversations', async () => {
    const records = (await createDevTeamReviewApi().listForManager(manager.id))
      .filter((record): record is TeamConversation => record.reviewStatus !== 'review-requested')
    openApp({ path, viewerApi: asManager, teamReviewApi: { ...createDevTeamReviewApi(), listForManager: async () => records } })
    await screen.findByRole('heading', { name: 'No flagged feedback' })
    expect(screen.getByText('0 flagged for review')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Show all conversations' }))
    expect(calls()).toHaveLength(4)
  })

  it('refuses the review queue to Agents, in the page and in the development API', async () => {
    const listForManager = vi.fn()
    openApp({ path, viewerApi: { getViewer: async () => agent }, teamReviewApi: { ...createDevTeamReviewApi(), listForManager } })
    await screen.findByRole('heading', { name: 'Page unavailable for your role' })
    expect(listForManager).not.toHaveBeenCalled()
    await expect(createDevTeamReviewApi().listForManager(agent.id)).rejects.toThrow()
  })
})
