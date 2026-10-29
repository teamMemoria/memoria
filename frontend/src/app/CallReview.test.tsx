import { act, fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AgentContext, CallReview } from '../types/callReview'
import type { Conversation } from '../features/conversations/conversations'
import {
  agent, callFixture, callPath, createDevCallApi, deferred, findingPath, openApp,
} from './TestSetup'

const conversation: Conversation = {
  id: 'C1042', topic: 'Refund request', agentId: agent.id,
  agentName: agent.displayName, date: '2026-10-08',
  automatedResult: 'needs-review', reviewStatus: 'feedback-ready',
}

describe('Agent call review', () => {
  it('connects conversations, feedback, evidence and the approved procedure, preserving filters and history', async () => {
    const search = '?q=Refund&status=feedback-ready'
    const { router } = openApp({ path: '/agent/conversations' + search })
    fireEvent.click(await screen.findByRole('link', { name: 'Open conversation C1042: Refund request' }))
    await screen.findByRole('heading', { name: 'Damaged jacket refund' })
    const feedback = screen.getByRole('region', { name: 'Automatic feedback' })
    expect(within(feedback).getByRole('link', { name: 'Procedure: Needs review' })).toBeTruthy()
    expect(within(feedback).getByText('Text only')).toBeTruthy()
    fireEvent.click(screen.getByRole('link', { name: 'View feedback' }))
    await screen.findByRole('heading', { name: 'Procedure finding' })
    expect(screen.getByText('I can offer you a refund.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Purchase verified at turn 13' }))
    const selected = screen.getByRole('button', { name: 'Select turn 13' })
    expect(selected.getAttribute('aria-pressed')).toBe('true')
    expect(within(selected.closest('tr')!).getByText('I’ve verified the purchase. The jacket is eligible.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'View step 2 of RP-01' }))
    const reference = screen.getByRole('dialog')
    expect(within(reference).getByText(/Verify the order, customer match and refund eligibility before offering a refund/)).toBeTruthy()
    fireEvent.click(within(reference).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Next' }).disabled).toBe(true)
    fireEvent.click(screen.getByRole('link', { name: 'Complete transcript' }))
    await screen.findByRole('heading', { name: 'Complete conversation' })
    expect(screen.getByText(/Your refund has been submitted to the original payment card/)).toBeTruthy()
    await act(() => router.navigate(-1))
    await screen.findByRole('heading', { name: 'Procedure finding' })
    expect(screen.getByRole('button', { name: 'Select turn 13' }).getAttribute('aria-pressed')).toBe('true')
    await act(() => router.navigate(1))
    await screen.findByRole('heading', { name: 'Complete conversation' })
    fireEvent.click(screen.getByRole('link', { name: 'Call overview' }))
    await screen.findByRole('heading', { name: 'Damaged jacket refund' })
    fireEvent.click(within(screen.getByRole('main')).getByRole('link', { name: 'Conversations' }))
    await screen.findByRole('table')
    expect(router.state.location.search).toBe(search)
    expect(screen.getByRole<HTMLInputElement>('searchbox', { name: 'Search calls' }).value).toBe('Refund')
    expect(screen.getByRole<HTMLSelectElement>('combobox', { name: 'Review status' }).value).toBe('feedback-ready')
  })

  it('searches owned calls, previews and commits status filters, clears no results and restores history', async () => {
    const records: Conversation[] = [
      { ...conversation, id: 'OLD', date: '2026-10-01', reviewStatus: 'review-complete' },
      { ...conversation, id: 'PRIVATE', agentId: 'another-agent' },
      conversation,
      { ...conversation, id: 'PROCESSING', automatedResult: 'processing', reviewStatus: null },
    ]
    const { router } = openApp({ conversationsApi: { listForAgent: async () => records } })
    const table = await screen.findByRole('table')
    expect(within(table).queryByText('PRIVATE')).toBeNull()
    expect(within(table).getAllByRole('link').map((link) => link.textContent)).toEqual(['C1042', 'PROCESSING', 'OLD'])
    const bar = screen.getByRole('group', { name: 'Filter conversations by status' })
    const ready = within(bar).getByRole('button', { name: 'Feedback ready: 1' })
    fireEvent.mouseEnter(ready)
    expect(within(table).queryByText('OLD')).toBeNull()
    expect(router.state.location.search).toBe('')
    fireEvent.click(ready)
    fireEvent.mouseLeave(bar)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'processing' } })
    await act(() => router.navigate(-1))
    expect(screen.getByRole<HTMLSelectElement>('combobox').value).toBe('feedback-ready')
    await act(() => router.navigate(1))
    expect(screen.getByRole<HTMLSelectElement>('combobox').value).toBe('processing')
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'no such call' } })
    expect(screen.getByRole('heading', { name: 'No matching conversations' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(router.state.location.search).toBe('')
    expect(within(table).getAllByRole('link')).toHaveLength(3)
  })

  it.each(['foreign owner', 'wrong ID', 'missing'] as const)('blocks a %s call returned for a direct link', async (kind) => {
    const call = await callFixture()
    if (kind === 'foreign owner') call.agentId = 'another-agent'
    if (kind === 'wrong ID') call.id = 'PRIVATE'
    openApp({ path: callPath, callApi: { ...createDevCallApi(), getCallForAgent: async () => kind === 'missing' ? null : call } })
    await screen.findByRole('heading', { name: 'Conversation unavailable' })
    expect(screen.queryByText(call.summary)).toBeNull()
    fireEvent.click(within(screen.getByRole('main')).getByRole('link', { name: 'Conversations' }))
    await screen.findByRole('table')
  })

  it('keeps processing calls distinct from completed feedback when opened from the list', async () => {
    const call = await callFixture({ status: 'processing' })
    openApp({ callApi: { ...createDevCallApi(), getCallForAgent: async () => call } })
    fireEvent.click(await screen.findByRole('link', { name: 'Open conversation C1042: Refund request' }))
    await screen.findByRole('heading', { name: 'Feedback is processing' })
    expect(screen.queryByRole('region', { name: 'Automatic feedback' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'View feedback' })).toBeNull()
  })

  it('shows the Manager decision separately from the original automated assessment', async () => {
    const call = await callFixture({ decision: {
      outcome: 'cannot-assess', reason: 'The reference was disputed after this audit.',
      feedback: 'No agent failure has been established.', managerName: 'Maya Chen',
      decidedAt: '2026-10-09T10:00:00Z',
    } })
    openApp({ path: callPath, callApi: { ...createDevCallApi(), getCallForAgent: async () => call } })
    const decision = await screen.findByRole('region', { name: 'Manager decision' })
    expect(within(decision).getByText('Cannot assess')).toBeTruthy()
    expect(within(decision).getByText('No agent failure has been established.')).toBeTruthy()
    expect(within(decision).getByText('Maya Chen')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Procedure: Needs review' })).toBeTruthy()
    expect(within(decision).queryByRole('button')).toBeNull()
  })

  it.each(['missing transcript', 'missing cited turn', 'disputed reference'] as const)('explains %s without treating missing evidence as agent failure', async (kind) => {
    const call = await callFixture()
    if (kind === 'missing transcript') call.transcript = null
    if (kind === 'missing cited turn') call.transcript!.turns = call.transcript!.turns.filter((turn) => turn.number !== 13)
    if (kind === 'disputed reference') call.references[0].status = 'disputed'
    openApp({ path: findingPath, callApi: { ...createDevCallApi(), getCallForAgent: async () => call } })
    await screen.findByRole('heading', { name: 'Cannot assess' })
    expect(screen.getByText('Missing evidence does not establish an agent error.')).toBeTruthy()
    expect(screen.queryByText(/Suggested next step:/)).toBeNull()
    if (kind === 'missing cited turn') {
      expect(screen.getByText('Cited transcript turn 13 is unavailable.')).toBeTruthy()
    }
    fireEvent.click(screen.getByRole('button', { name: 'View step 2 of RP-01' }))
    const dialog = screen.getByRole('dialog')
    if (kind === 'disputed reference') {
      expect(within(dialog).getByRole('heading', { name: 'Approved reference unavailable' })).toBeTruthy()
      expect(within(dialog).queryByText(/Verify the order/)).toBeNull()
    } else {
      expect(within(dialog).getByText(/Verify the order/)).toBeTruthy()
    }
  })

  it('labels a partial transcript and returns to the call without inventing the missing passage', async () => {
    const call = await callFixture()
    call.transcript = { complete: false, turns: call.transcript!.turns.slice(0, 8), unavailableReason: 'Only the first eight turns are available.' }
    openApp({ path: callPath + '/transcript', callApi: { ...createDevCallApi(), getCallForAgent: async () => call } })
    await screen.findByRole('heading', { name: 'Available transcript' })
    expect(screen.getByText('Only the first eight turns are available.')).toBeTruthy()
    expect(screen.queryByText('I’ve verified the purchase. The jacket is eligible.')).toBeNull()
    fireEvent.click(screen.getByRole('link', { name: 'Call overview' }))
    await screen.findByRole('heading', { name: call.topic })
  })

  it.each([
    { path: '/agent/conversations', heading: 'My conversations', list: true },
    { path: callPath, heading: 'Damaged jacket refund', list: false },
    { path: findingPath, heading: 'Procedure finding', list: false },
  ])('recovers from a failed request at $path through the visible retry action', async ({ path, heading, list }) => {
    const call = await callFixture()
    const response = deferred<CallReview | Conversation[]>()
    const request = vi.fn().mockRejectedValueOnce(new Error('Internal API failure')).mockReturnValueOnce(response.promise)
    openApp({ path, conversationsApi: { listForAgent: request }, callApi: { ...createDevCallApi(), getCallForAgent: request } })
    await screen.findByRole('alert')
    expect(screen.queryByText('Internal API failure')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByRole('status').textContent).toContain('Loading')
    if (list) expect(screen.getByRole<HTMLInputElement>('searchbox').disabled).toBe(true)
    await act(() => response.resolve(list ? [conversation] : call))
    await screen.findByRole('heading', { name: heading })
    expect(screen.queryByRole('alert')).toBeNull()
    expect(request).toHaveBeenCalledTimes(2)
    if (list) expect(screen.getByRole<HTMLInputElement>('searchbox').disabled).toBe(false)
  })

  it('ignores an old call response after navigating to a different conversation', async () => {
    const previous = deferred<CallReview | null>()
    const current = deferred<CallReview | null>()
    const getCallForAgent = vi.fn().mockReturnValueOnce(previous.promise).mockReturnValueOnce(current.promise)
    const { router } = openApp({ path: callPath, callApi: { ...createDevCallApi(), getCallForAgent } })
    await screen.findByText('Loading conversation…')
    await act(() => router.navigate('/agent/conversations/OTHER'))
    await act(() => current.resolve(null))
    await screen.findByRole('heading', { name: 'Conversation unavailable' })
    await act(async () => previous.resolve(await callFixture()))
    expect(screen.queryByText('Damaged jacket refund')).toBeNull()
    expect(screen.getByRole('heading', { name: 'Conversation unavailable' })).toBeTruthy()
  })

  it('does not let an abandoned list request overwrite a new visit', async () => {
    const previous = deferred<Conversation[]>()
    const listForAgent = vi.fn().mockReturnValueOnce(previous.promise).mockResolvedValueOnce([conversation])
    openApp({ conversationsApi: { listForAgent } })
    await screen.findByText('Loading your conversations…')
    fireEvent.click(screen.getByRole('link', { name: 'Knowledge Base' }))
    await screen.findByRole('list', { name: 'Approved entries' })
    fireEvent.click(screen.getByRole('link', { name: 'Conversations' }))
    const table = await screen.findByRole('table')
    await act(() => previous.resolve([{ ...conversation, id: 'OLD-RESPONSE' }]))
    expect(within(table).getByText('C1042')).toBeTruthy()
    expect(within(table).queryByText('OLD-RESPONSE')).toBeNull()
  })

  it('opens the explicitly linked reference and refuses an unrelated one', async () => {
    const call = await callFixture()
    call.references.push({ ...call.references[0], id: 'RP-02', title: 'Delivery procedure' })
    call.criteria[1].referenceId = 'RP-02'
    const { router } = openApp({
      path: callPath + '/transcript?reference=RP-02#approved-reference',
      callApi: { ...createDevCallApi(), getCallForAgent: async () => call },
    })
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: 'Delivery procedure' })).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    await act(() => router.navigate(callPath + '/transcript?reference=UNRELATED#approved-reference'))
    expect(within(screen.getByRole('dialog')).getByRole('heading', { name: 'Approved reference unavailable' })).toBeTruthy()
    expect(within(screen.getByRole('dialog')).queryByText('Delivery procedure')).toBeNull()
  })
})

describe('Agent context', () => {
  const note = 'The customer was verified by chat before this call.'
  const contextField = () => screen.findByLabelText<HTMLTextAreaElement>('Context for this call')

  it('saves context without requesting a Manager review and keeps it after navigating away', async () => {
    const callApi = createDevCallApi()
    const requestReview = vi.spyOn(callApi, 'requestReview')
    const { router } = openApp({ path: findingPath, callApi })
    fireEvent.change(await contextField(), { target: { value: note } })
    fireEvent.click(screen.getByRole('button', { name: 'Save context' }))
    await screen.findByText(/^Saved /)
    expect(requestReview).not.toHaveBeenCalled()
    expect(screen.getByRole('heading', { name: 'Automatic feedback' })).toBeTruthy()
    await act(() => router.navigate(callPath))
    await act(() => router.navigate(findingPath))
    expect((await contextField()).value).toBe(note)
  })

  it('shows an error and keeps the typed text when saving fails', async () => {
    const callApi = { ...createDevCallApi(), saveContext: vi.fn().mockRejectedValue(new Error('Offline')) }
    openApp({ path: findingPath, callApi })
    fireEvent.change(await contextField(), { target: { value: note } })
    fireEvent.click(screen.getByRole('button', { name: 'Save context' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Context could not be saved. Please try again.')
    expect((await contextField()).value).toBe(note)
    expect(screen.queryByText(/^Saved /)).toBeNull()
  })

  it('sends one save while a save is in progress', async () => {
    const save = deferred<AgentContext>()
    const saveContext = vi.fn(() => save.promise)
    openApp({ path: findingPath, callApi: { ...createDevCallApi(), saveContext } })
    fireEvent.change(await contextField(), { target: { value: note } })
    fireEvent.click(screen.getByRole('button', { name: 'Save context' }))
    fireEvent.click(screen.getByRole('button', { name: 'Saving…' }))
    expect(saveContext).toHaveBeenCalledTimes(1)
    await act(() => save.resolve({ text: note, savedAt: '2026-10-29T15:00:00Z' }))
    expect(screen.getByText('Saved Oct 29, 2026, 3:00 PM UTC')).toBeTruthy()
  })
})
