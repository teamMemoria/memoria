import { act, fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { createDevKnowledgeReviewApi } from '../lib/devKnowledgeReview'
import type { KnowledgeDraft } from '../types/knowledge'
import { agent, manager, openApp } from './TestSetup'

const path = '/manager/knowledge'
const asManager = { getViewer: async () => manager }
const rows = () => within(screen.getByRole('table')).getAllByRole('link').map((link) => link.textContent)

describe('Manager knowledge drafts', () => {
  it('shows each tab with the right entries and counts that match the API', async () => {
    openApp({ path, viewerApi: asManager })
    await screen.findByRole('table')
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Pending (3)', 'Approved (1)', 'Flagged (1)', 'Rejected (1)',
    ])
    expect(rows()).toEqual(['Exchanges for damaged items', 'Refund timing for card payments', 'Missing parcel claims'])
    const row = screen.getByRole('link', { name: 'Exchanges for damaged items' }).closest('tr')!
    expect(within(row).getByText('Returns')).toBeTruthy()
    expect(within(row).getByText('3 conversations')).toBeTruthy()
    expect(within(row).getByText('Oct 27, 2026')).toBeTruthy()
    expect(within(row).getByText('Pending')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Approved (1)' }))
    expect(rows()).toEqual(['Refund handling'])
    fireEvent.click(screen.getByRole('tab', { name: 'Flagged (1)' }))
    expect(rows()).toEqual(['Store credit expiry'])
    fireEvent.click(screen.getByRole('tab', { name: 'Rejected (1)' }))
    expect(rows()).toEqual(['Refunds without a receipt'])
  })

  it('searches within a tab, opens an entry and keeps the tab and search on return', async () => {
    const { router } = openApp({ path, viewerApi: asManager })
    const search = await screen.findByRole('searchbox', { name: 'Search knowledge entries' })
    fireEvent.change(search, { target: { value: 'no such entry' } })
    expect(screen.getByRole('heading', { name: 'No matching entries' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }))
    fireEvent.change(search, { target: { value: 'refund' } })
    expect(rows()).toEqual(['Refund timing for card payments'])
    fireEvent.click(screen.getByRole('tab', { name: 'Rejected (1)' }))
    expect(rows()).toEqual(['Refunds without a receipt'])
    fireEvent.click(screen.getByRole('link', { name: 'Refunds without a receipt' }))
    await screen.findByRole('heading', { name: 'Review KD-095' })
    fireEvent.click(screen.getByRole('link', { name: 'Knowledge drafts' }))
    await screen.findByRole('table')
    expect(router.state.location.search).toBe('?q=refund&tab=rejected')
    expect(screen.getByRole('tab', { name: 'Rejected (1)' }).getAttribute('aria-selected')).toBe('true')
    expect(rows()).toEqual(['Refunds without a receipt'])
  })

  it('refreshes counts and rows when returning after a decision', async () => {
    const before = await createDevKnowledgeReviewApi().listForManager(manager.id)
    const after: KnowledgeDraft[] = before.map((entry) =>
      entry.id === 'KD-103' ? { ...entry, status: 'approved' } : entry,
    )
    const listForManager = vi.fn().mockResolvedValueOnce(before).mockResolvedValueOnce(after)
    const { router } = openApp({ path, viewerApi: asManager, knowledgeReviewApi: { listForManager } })
    await screen.findByRole('tab', { name: 'Pending (3)' })
    fireEvent.click(screen.getByRole('link', { name: 'Refund timing for card payments' }))
    await screen.findByRole('heading', { name: 'Review KD-103' })
    await act(() => router.navigate(path))
    await screen.findByRole('tab', { name: 'Pending (2)' })
    expect(screen.getByRole('tab', { name: 'Approved (2)' })).toBeTruthy()
    expect(rows()).not.toContain('Refund timing for card payments')
    expect(listForManager).toHaveBeenCalledTimes(2)
  })

  it('shows loading, error with retry, and empty states', async () => {
    const listForManager = vi.fn()
      .mockRejectedValueOnce(new Error('Internal details'))
      .mockResolvedValueOnce([])
    openApp({ path, viewerApi: asManager, knowledgeReviewApi: { listForManager } })
    expect(await screen.findByText('Loading knowledge drafts…')).toBeTruthy()
    expect((await screen.findByRole('alert')).textContent).toBe('Knowledge drafts could not be loaded. Please try again.')
    expect(screen.queryByText('Internal details')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByRole('heading', { name: 'No pending entries' })
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Pending (0)', 'Approved (0)', 'Flagged (0)', 'Rejected (0)',
    ])
  })

  it('refuses the draft queue to Agents, in the page and in the development API', async () => {
    const listForManager = vi.fn()
    openApp({ path, viewerApi: { getViewer: async () => agent }, knowledgeReviewApi: { listForManager } })
    await screen.findByRole('heading', { name: 'Page unavailable for your role' })
    expect(listForManager).not.toHaveBeenCalled()
    expect(screen.queryByRole('table')).toBeNull()
    await expect(createDevKnowledgeReviewApi().listForManager(agent.id)).rejects.toThrow()
  })
})
