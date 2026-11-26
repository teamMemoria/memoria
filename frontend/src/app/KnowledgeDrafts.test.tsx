import { act, fireEvent, screen, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { createDevKnowledgeReviewApi } from '../test/devKnowledgeReview'
import { agent, input, manager, openApp, press } from './TestSetup'

const path = '/manager/knowledge'
const openQueue = (knowledgeReviewApi = createDevKnowledgeReviewApi()) => openApp({ path, as: manager, knowledgeReviewApi })
const rows = () => within(screen.getByRole('table')).getAllByRole('row').slice(1)
  .map((row) => within(row).getAllByRole('link')[0].textContent)
const tabs = () => screen.getAllByRole('tab').map((tab) => tab.textContent)
const search = (value: string) => input('Search knowledge entries', value)

it.each(['development', 'simulation'])('uses short draft labels and keeps the two layers in %s', async (mode) => {
  vi.stubEnv('MODE', mode)
  const api = createDevKnowledgeReviewApi()
  const pending = (await api.listForManager(manager.id)).filter(({ status }) => status === 'draft')
  const policyQuestion = 'How should an agent answer whether a specific size is in stock or coming back?'
  const draftQuestion = 'What troubleshooting options can the Agent suggest when site search fails?'
  const guidance = 'Check the site version. Version 2.4 uses the new search. Ask the customer to try again.'
  const entries = [
    { ...pending[0], layer: mode === 'development' ? 'layer1' as const : undefined, title: policyQuestion, topic: 'Stock and restock answers' },
    { ...pending[1], layer: mode === 'development' ? 'layer2' as const : undefined, title: draftQuestion, topic: 'Site search troubleshooting', paragraphs: [guidance] },
    pending[2],
  ]
  const { router } = openQueue({
    ...api,
    listForManager: async () => entries,
    getForManager: async (_manager, id) => {
      const entry = entries.find((record) => record.id === id)
      return entry ? { entry, canDecide: false } : null
    },
  })
  const layer1 = within(await screen.findByRole('table', { name: 'Layer 1 policies' }))
  const policyPath = layer1.getByRole('link', { name: 'Stock and restocks' }).getAttribute('href')!
  expect(layer1.getByRole('cell', { name: 'Stock' })).toBeTruthy()
  expect(layer1.queryByRole('columnheader', { name: 'Sources' })).toBeNull()
  const layer2 = screen.getByRole('table', { name: 'Layer 2 drafts' })
  expect(within(layer2).getByRole('columnheader', { name: 'Sources' })).toBeTruthy()
  expect(screen.getByRole('table', { name: 'Other drafts' })).toBeTruthy()
  for (const query of ['website', 'site search troubleshooting', 'fixing site search']) {
    search(query)
    expect(screen.getAllByRole('table')).toEqual([layer2])
  }
  fireEvent.click(within(layer2).getByRole('link', { name: 'Fixing site search' }))
  const document = await screen.findByRole('region', { name: 'Draft document viewer' })
  expect(screen.getByRole('region', { name: 'Sources' }).nextElementSibling).toBe(document)
  const article = within(document).getByRole('article', { name: draftQuestion })
  expect(within(article).getAllByRole('paragraph').map((paragraph) => paragraph.textContent)).toEqual([
    'Check the site version. Version 2.4 uses the new search.',
    'Ask the customer to try again.',
  ])
  await act(() => router.navigate(policyPath))
  await screen.findByRole('heading', { name: 'Stock and restocks', level: 1 })
  expect(screen.queryByRole('region', { name: 'Sources' })).toBeNull()
  expect(screen.getByRole('region', { name: 'Draft document viewer' })).toBeTruthy()
})

it('limits the hosted demo queue and counts to the two demo layers', async () => {
  vi.stubEnv('VITE_DEMO_LOGIN', 'true')
  vi.stubEnv('VITE_HOSTED_DEMO_SCORECARDS', 'true')
  const api = createDevKnowledgeReviewApi()
  const pending = (await api.listForManager(manager.id)).filter(({ status }) => status === 'draft')
  pending[0] = { ...pending[0], layer: 'layer1' }
  pending[1] = {
    ...pending[1], layer: 'layer2',
    title: 'What troubleshooting options can the Agent suggest when site search fails?',
    topic: 'Site search troubleshooting',
  }
  openQueue({ ...api, listForManager: async () => pending })
  await screen.findByRole('table', { name: 'Layer 1 policies' })
  const layer2 = screen.getByRole('table', { name: 'Layer 2 drafts' })
  expect(within(layer2).getByRole('link', { name: 'Fixing site search' })).toBeTruthy()
  expect(within(layer2).getByRole('cell', { name: 'Website' })).toBeTruthy()
  expect(screen.queryByRole('table', { name: 'Other drafts' })).toBeNull()
  expect(screen.getByRole('tab', { name: 'Pending review (2)' })).toBeTruthy()
})

it('keeps tab totals, hover preview and selected status in sync', async () => {
  openQueue()
  await screen.findByRole('table')
  expect(tabs()).toEqual(['Pending review (3)', 'Approved (1)', 'Flagged (1)', 'Rejected (1)'])
  expect(rows()).toEqual(['Exchanges for damaged items', 'Refund timing for card payments', 'Missing parcel claims'])
  const bar = within(screen.getByRole('figure', { name: 'Knowledge draft counts' }))
  const approved = bar.getByRole('button', { name: 'Approved (1)' })
  act(() => approved.dispatchEvent(Object.assign(new MouseEvent('pointerover', { bubbles: true }), { pointerType: 'mouse' })))
  expect(rows()).toEqual(['Refund handling'])
  fireEvent.click(approved)
  expect(screen.getByRole('tab', { name: 'Approved (1)' }).getAttribute('aria-selected')).toBe('true')
  for (const [tab, title] of [['Flagged (1)', 'Store credit expiry'], ['Rejected (1)', 'Refunds without a receipt']]) {
    fireEvent.click(screen.getByRole('tab', { name: tab }))
    expect(rows()).toEqual([title])
  }
})

it('keeps the tab and URL-backed search on return from a draft', async () => {
  const { router } = openQueue()
  await screen.findByRole('searchbox')
  search('no such entry')
  expect(screen.getByRole('heading', { name: 'No matching entries' })).toBeTruthy()
  press('Clear search')
  search('refund')
  fireEvent.click(screen.getByRole('tab', { name: 'Rejected (1)' }))
  expect(rows()).toEqual(['Refunds without a receipt'])
  fireEvent.click(screen.getByRole('link', { name: rows()[0]! }))
  await screen.findByRole('heading', { name: 'Refunds without a receipt', level: 1 })
  fireEvent.click(screen.getByRole('link', { name: 'Knowledge drafts' }))
  await screen.findByRole('table')
  expect(router.state.location.search).toBe('?q=refund&tab=rejected')
  expect(rows()).toEqual(['Refunds without a receipt'])
})

it('recovers from an error and shows an empty queue', async () => {
  const listForManager = vi.fn().mockRejectedValueOnce(new Error('Internal details')).mockResolvedValueOnce([])
  openQueue({ ...createDevKnowledgeReviewApi(), listForManager })
  expect((await screen.findByRole('alert')).textContent).toBe('Knowledge drafts could not be loaded. Please try again.')
  expect(screen.queryByText('Internal details')).toBeNull()
  press('Try again')
  await screen.findByRole('heading', { name: 'No pending review entries' })
  expect(screen.queryByRole('figure', { name: 'Knowledge draft counts' })).toBeNull()
  expect(tabs()).toEqual(['Pending review (0)', 'Approved (0)', 'Flagged (0)', 'Rejected (0)'])
  expect(listForManager).toHaveBeenCalledTimes(2)
})

it('refuses Agents at the Manager route and data boundary', async () => {
  const api = createDevKnowledgeReviewApi()
  const listForManager = vi.spyOn(api, 'listForManager')
  openApp({ path, knowledgeReviewApi: api })
  await screen.findByRole('heading', { name: 'Page unavailable for your role' })
  expect(listForManager).not.toHaveBeenCalled()
  expect(screen.queryByRole('table')).toBeNull()
  await expect(listForManager(agent.id)).rejects.toThrow()
})
