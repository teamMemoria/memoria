import { act, fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ApprovedKnowledgeApi, KnowledgeEntry } from '../types/knowledge'
import { agent, callFixture, deferred, openApp } from './TestSetup'

function apiFor(entries: KnowledgeEntry[]): ApprovedKnowledgeApi {
  return {
    listForAgent: async () => entries,
    getForAgent: async (_agentId, id) => entries.find((entry) => entry.id === id) ?? null,
  }
}

describe('Agent approved knowledge', () => {
  it('opens knowledge from the sidebar, searches, reads an article and retains search through return and history', async () => {
    const { router } = openApp()
    await screen.findByRole('heading', { name: 'My conversations' })
    fireEvent.click(screen.getByRole('link', { name: 'Knowledge Base' }))
    await screen.findByRole('list', { name: 'Approved entries' })
    const search = screen.getByRole('searchbox', { name: 'Search approved knowledge' })
    fireEvent.change(search, { target: { value: 'no such guidance' } })
    expect(screen.getByRole('heading', { name: 'No matching guidance' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }))
    fireEvent.change(search, { target: { value: 'refund' } })
    fireEvent.click(screen.getByRole('link', { name: 'Open Refund handling, RP-01 version 1' }))
    const article = await screen.findByRole('region', { name: 'Refund handling' })
    expect(within(article).getByText('Read-only approved guidance.')).toBeTruthy()
    expect(within(article).getByText(/Verify the order, customer match and refund eligibility/).textContent).toBe('Verify the order, customer match and refund eligibility before offering a refund.')
    expect(within(article).queryByRole('button')).toBeNull()
    expect(screen.getByRole('link', { name: 'Knowledge Base' }).getAttribute('aria-current')).toBe('page')
    await act(() => router.navigate(-1))
    expect((await screen.findByRole<HTMLInputElement>('searchbox')).value).toBe('refund')
    await act(() => router.navigate(1))
    await screen.findByRole('region', { name: 'Refund handling' })
    fireEvent.click(screen.getByRole('link', { name: 'Approved knowledge' }))
    expect((await screen.findByRole<HTMLInputElement>('searchbox')).value).toBe('refund')
    expect(router.state.location.search).toBe('?q=refund')
  })

  it('presents the approved procedure with its original wording and separate reference details', async () => {
    const entry = (await callFixture()).references[0]
    openApp({ path: '/agent/knowledge/RP-01', knowledgeApi: apiFor([entry]) })
    const article = await screen.findByRole('region', { name: 'Refund handling' })
    expect(within(article).getByRole('heading', { name: entry.title, level: 1 })).toBeTruthy()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    const breadcrumb = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(within(breadcrumb).getByText(entry.title).getAttribute('aria-current')).toBe('page')
    const steps = within(article).getByRole('list', { name: 'Procedure steps' })
    const items = within(steps).getAllByRole('listitem')
    expect(items).toHaveLength(entry.steps.length)
    for (const [index, step] of entry.steps.entries()) {
      expect(items[index].textContent).toContain(step.text)
    }
    expect(within(steps).getByRole('heading', { name: 'Verify the purchase.' })).toBeTruthy()
    expect(within(items[1]).getByText('before offering a refund.').tagName).toBe('STRONG')
    const details = within(article).getByRole('complementary', { name: 'Reference details' })
    expect(within(details).getByText(entry.owner!)).toBeTruthy()
    expect(within(details).getByText(entry.source!.title)).toBeTruthy()
    expect(within(details).getAllByText('Not supplied')).toHaveLength(2)
    expect(within(article).queryByRole('button')).toBeNull()
  })

  it.each([
    { id: 'RP-02', version: 'v1', kind: 'procedure' as const },
    { id: 'RP-01', version: 'v2', kind: 'procedure' as const },
    { id: 'RP-01', version: 'v1', kind: 'knowledge' as const },
  ])('retains another entry’s content without applying refund-specific headings: %j', async (record) => {
    const reference = (await callFixture()).references[0]
    const entry = { ...reference, ...record, steps: [{ number: 2, text: 'Use the approved delivery instructions.' }] }
    openApp({ path: `/agent/knowledge/${entry.id}`, knowledgeApi: apiFor([entry]) })
    const steps = await screen.findByRole('list', { name: 'Procedure steps' })
    expect(within(steps).getByText(entry.steps[0].text)).toBeTruthy()
    expect(within(steps).queryByRole('heading')).toBeNull()
  })

  it('keeps a text-only entry and its available source link readable', async () => {
    const reference = (await callFixture()).references[0]
    const entry = { ...reference, steps: [], source: { title: 'Approved reference', url: 'https://example.test/reference' } }
    openApp({ path: '/agent/knowledge/RP-01', knowledgeApi: apiFor([entry]) })
    const article = await screen.findByRole('region', { name: 'Refund handling' })
    expect(within(article).getByRole('link', { name: entry.source.title }).getAttribute('href')).toBe(entry.source.url)
    expect(within(article).getByText(entry.paragraphs[0])).toBeTruthy()
    expect(within(article).queryByRole('list', { name: 'Procedure steps' })).toBeNull()
  })

  it('excludes drafts and other agents’ guidance even when the API returns them', async () => {
    const reference = (await callFixture()).references[0]
    openApp({ path: '/agent/knowledge', knowledgeApi: apiFor([
      reference,
      { ...reference, id: 'DRAFT', title: 'Unverified guidance', status: 'draft' },
      { ...reference, id: 'PRIVATE', title: 'Private guidance', availableToAgentIds: ['another-agent'] },
    ]) })
    const list = await screen.findByRole('list', { name: 'Approved entries' })
    expect(within(list).getAllByRole('link')).toHaveLength(1)
    expect(screen.queryByText('Unverified guidance')).toBeNull()
    expect(screen.queryByText('Private guidance')).toBeNull()
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'guidance' } })
    expect(screen.getByRole('heading', { name: 'No matching guidance' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /approve|reject|edit/i })).toBeNull()
  })

  it.each(['draft', 'foreign', 'missing'] as const)('refuses a direct-linked %s entry and returns to approved knowledge', async (kind) => {
    const reference = (await callFixture()).references[0]
    if (kind === 'draft') reference.status = 'draft'
    if (kind === 'foreign') reference.availableToAgentIds = ['another-agent']
    const api = apiFor(kind === 'missing' ? [] : [reference])
    openApp({ path: '/agent/knowledge/RP-01', knowledgeApi: api })
    await screen.findByRole('heading', { name: 'Entry unavailable' })
    expect(screen.queryByText(/Verify the order, customer match/)).toBeNull()
    fireEvent.click(screen.getByRole('link', { name: 'Approved knowledge' }))
    await screen.findByRole('heading', { name: 'No approved guidance yet' })
  })

  it.each([
    { path: '/agent/knowledge', detail: false },
    { path: '/agent/knowledge/RP-01', detail: true },
  ])('recovers a failed knowledge request at $path through retry', async ({ path, detail }) => {
    const reference = (await callFixture()).references[0]
    const response = deferred<KnowledgeEntry[] | KnowledgeEntry>()
    const request = vi.fn().mockRejectedValueOnce(new Error('Internal source failure')).mockReturnValueOnce(response.promise)
    const api = apiFor([reference])
    if (detail) api.getForAgent = request
    else api.listForAgent = request
    openApp({ path, knowledgeApi: api })
    await screen.findByRole('alert')
    expect(screen.queryByText('Internal source failure')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByRole('status').textContent).toContain('Loading approved knowledge')
    await act(() => response.resolve(detail ? reference : [reference]))
    if (detail) await screen.findByRole('region', { name: 'Refund handling' })
    else await screen.findByRole('list', { name: 'Approved entries' })
    expect(request).toHaveBeenCalledTimes(2)
    expect(request).toHaveBeenLastCalledWith(...(detail ? [agent.id, 'RP-01'] : [agent.id]))
  })

  it('ignores a late failure after opening another approved article', async () => {
    const reference = (await callFixture()).references[0]
    const previous = deferred<KnowledgeEntry | null>()
    const current = deferred<KnowledgeEntry | null>()
    const getForAgent = vi.fn().mockReturnValueOnce(previous.promise).mockReturnValueOnce(current.promise)
    const { router } = openApp({
      path: '/agent/knowledge/RP-01',
      knowledgeApi: { listForAgent: async () => [], getForAgent },
    })
    await screen.findByText('Loading approved knowledge…')
    await act(() => router.navigate('/agent/knowledge/RP-02'))
    await act(() => current.resolve({ ...reference, id: 'RP-02', title: 'Delivery procedure' }))
    await screen.findByRole('region', { name: 'Delivery procedure' })
    await act(() => previous.reject(new Error('Late request failed')))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('region', { name: 'Delivery procedure' })).toBeTruthy()
  })

  it('explains disconnected knowledge without inventing articles or offering a nonfunctional retry', async () => {
    openApp({ path: '/agent/knowledge', knowledgeApi: null })
    await screen.findByRole('heading', { name: 'Knowledge unavailable' })
    expect(screen.queryByRole('list', { name: 'Approved entries' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
    fireEvent.click(screen.getByRole('link', { name: 'Conversations' }))
    await screen.findByRole('table')
  })
})
