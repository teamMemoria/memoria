import { act, fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AgentContext, CallReview } from '../types/callReview'
import type { Conversation } from '../features/conversations/conversations'
import {
  agent, chooseOption, button, callFixture, callPath, createDevCallApi, deferred, findingPath, openApp, openCall, press,
} from './TestSetup'

const conversation: Conversation = {
  id: 'C1042', topic: 'Refund request', agentId: agent.id,
  agentName: agent.displayName, date: '2026-10-08',
  automatedResult: 'needs-review', reviewStatus: 'feedback-ready',
}

describe('Agent call review', () => {
  it('shows the saved overall percentage on the conversation overview', async () => {
    const call = await callFixture()
    call.overallScoring = {
      score: 81.25, coverage: 62.5, reason: null,
      weights: { procedure: 25, completeness: 25, 'communication-style': 25, 'answer-support': 25 },
      profileId: 'evaluation-form', profileVersion: '2',
    }
    openCall(call)
    expect(await screen.findByText('Overall 81%')).toBeTruthy()
  })

  it('colors the overview scores using the same rounded bands as the score bar', async () => {
    const call = await callFixture({ sourceId: '7388', topic: 'Website' })
    call.assessmentSource = 'simulation'
    const scores = { procedure: 79.5, completeness: 59.5, 'answer-support': 59.4, 'communication-style': null }
    call.criteria = call.criteria.map((criterion) => ({
      ...criterion,
      scoring: {
        score: scores[criterion.id], earned: 0, assessable: 0, possible: 100, coverage: 0,
        inventoryComplete: true, processingError: null, checks: [], limitations: [], interpretationLimits: [],
      },
    }))
    call.overallScoring = {
      score: 72, coverage: 75, reason: null, weights: null, profileId: null, profileVersion: null,
    }
    openCall(call)
    await screen.findByRole('heading', { name: 'ABCD 7388', level: 1 })
    const metadata = within(screen.getByRole('list', { name: 'Call details' }))
    expect(metadata.getByText('Website')).toBeTruthy()
    expect(metadata.queryByText('ABCD 7388')).toBeNull()
    const overview = screen.getByRole('region', { name: 'Assessment scores' })
    expect(within(overview).getByText('72%').closest('[data-score-tone]')?.getAttribute('data-score-tone')).toBe('attention')
    for (const [name, tone] of [
      ['Procedure: 80%', 'positive'],
      ['Completeness: 60%', 'attention'],
      ['Answer support: 59%', 'negative'],
      ['Communication style: Not scored', undefined],
    ]) {
      expect(within(overview).getByRole('link', { name }).closest('[data-score-tone]')?.getAttribute('data-score-tone')).toBe(tone)
    }
  })

  it('ranks only owned demo calls and keeps the score bar and dropdown in sync', async () => {
    vi.stubEnv('MODE', 'simulation')
    const records = [63, 91, 12].map((simulationScore, index) => ({
      ...conversation,
      id: `demo-${index}`,
      sourceId: String(9901 + index),
      agentId: index === 2 ? 'another-agent' : agent.id,
      simulationScore,
    }))
    const { router } = openApp({
      path: '/agent/conversations',
      conversationsApi: { listForAgent: async () => records },
    })
    const table = await screen.findByRole('table')
    const calls = () => within(table).getAllByRole('link').map((link) => link.textContent)
    expect(calls()).toEqual(['ABCD 9902', 'ABCD 9901'])
    expect(screen.queryByRole('button', { name: /Below 60%/ })).toBeNull()

    const dropdown = screen.getByRole('combobox', { name: 'Overall score' })
    await chooseOption('60–79%', 'Overall score')
    expect(calls()).toEqual(['ABCD 9901'])
    expect(router.state.location.search).toBe('?status=middle')
    const band = screen.getByRole('button', { name: '60–79% (1)' })
    expect(band.getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(band)
    expect(dropdown.textContent).toContain('All scores')
    expect(calls()).toEqual(['ABCD 9902', 'ABCD 9901'])
  })

  it('shows Cannot assess for an older zero-evidence midpoint and keeps an evidenced 50%', async () => {
    const call = await callFixture()
    const scoring = {
      score: 50, earned: 0, assessable: 0, possible: 100, coverage: 0,
      inventoryComplete: true, processingError: null, checks: [],
      limitations: ['The policy conditions could not be verified.'], interpretationLimits: [],
    }
    call.criteria = call.criteria.map((criterion) => ({
      ...criterion,
      scoring: criterion.id === 'procedure' ? scoring
        : criterion.id === 'answer-support' ? { ...scoring, assessable: 100, earned: 50, coverage: 100 }
        : criterion.scoring,
    }))
    call.overallScoring = {
      score: 60, coverage: 75, reason: null,
      weights: { procedure: 25, completeness: 25, 'communication-style': 25, 'answer-support': 25 },
      profileId: 'evaluation-form', profileVersion: '2',
    }
    openCall(call)
    expect(await screen.findByText('Overall Cannot assess')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Procedure: Cannot assess' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Answer support: 50%' })).toBeTruthy()
  })

  it('connects conversations, feedback, evidence and the approved procedure, preserving filters and history', async () => {
    const search = '?q=Refund&status=feedback-ready'
    const { router } = openApp({ path: '/agent/conversations' + search })
    fireEvent.click(await screen.findByRole('link', { name: 'Open conversation C1042: Refund request' }))
    await screen.findByRole('heading', { name: 'Call C1042' })
    const feedback = screen.getByRole('region', { name: 'Automatic feedback' })
    expect(within(feedback).getByRole('link', { name: 'Procedure: Needs review' })).toBeTruthy()
    expect(within(feedback).queryByText('Text only')).toBeNull()
    fireEvent.click(screen.getByRole('link', { name: 'View feedback' }))
    await screen.findByRole('heading', { name: 'Procedure finding' })
    expect(screen.getByText('I can offer you a refund.')).toBeTruthy()
    const selected = screen.getByRole('button', { name: 'Select turn 13' })
    fireEvent.click(selected)
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
    await screen.findByRole('heading', { name: 'Call C1042' })
    fireEvent.click(within(screen.getByRole('main')).getByRole('link', { name: 'Conversations' }))
    await screen.findByRole('table')
    expect(router.state.location.search).toBe(search)
    expect(screen.getByRole<HTMLInputElement>('searchbox', { name: 'Search calls' }).value).toBe('Refund')
    expect(screen.getByRole('combobox', { name: 'Review status' }).textContent).toContain('Feedback ready')
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
    await chooseOption('Processing')
    await act(() => router.navigate(-1))
    expect(screen.getByRole('combobox').textContent).toContain('Feedback ready')
    await act(() => router.navigate(1))
    expect(screen.getByRole('combobox').textContent).toContain('Processing')
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
    openCall(kind === 'missing' ? null : call)
    await screen.findByRole('heading', { name: 'Conversation unavailable' })
    expect(screen.queryByText(call.summary)).toBeNull()
    fireEvent.click(within(screen.getByRole('main')).getByRole('link', { name: 'Conversations' }))
    await screen.findByRole('table')
  })

  it.each([
    ['processing', 'Feedback is processing'],
    ['unavailable', 'Assessment unavailable'],
    ['partial', 'Assessment incomplete'],
  ] as const)('separates %s calls from completed feedback', async (status, heading) => {
    openCall(await callFixture({ status, findings: [] }))
    await screen.findByRole('heading', { name: heading })
    expect(Boolean(screen.queryByRole('region', { name: 'Automatic feedback' }))).toBe(status === 'partial')
    expect(screen.queryByRole('link', { name: 'View feedback' })).toBeNull()
    if (status === 'unavailable') {
      fireEvent.click(screen.getByRole('link', { name: 'Transcript' }))
      await screen.findByRole('heading', { name: 'Complete conversation' })
    }
  })

  it('shows the Manager decision separately from the original automated assessment', async () => {
    const call = await callFixture({ decision: {
      outcome: 'cannot-assess', reason: 'The reference was disputed after this audit.',
      feedback: 'No agent failure has been established.', managerName: 'Maya Chen',
      decidedAt: '2026-10-09T10:00:00Z',
    } })
    openCall(call)
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
    openCall(call, findingPath)
    await screen.findByRole('heading', { name: 'Cannot assess' })
    expect(screen.getByText('Missing evidence does not establish an agent error.')).toBeTruthy()
    expect(screen.queryByText(/Suggested next step:/)).toBeNull()
    if (kind === 'missing cited turn') {
      expect(screen.getByText('Cited transcript turn 13 is unavailable.')).toBeTruthy()
    }
    press('View step 2 of RP-01')
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
    openCall(call, callPath + '/transcript')
    await screen.findByRole('heading', { name: 'Available transcript' })
    expect(screen.getByText('Only the first eight turns are available.')).toBeTruthy()
    expect(screen.queryByText('I’ve verified the purchase. The jacket is eligible.')).toBeNull()
    fireEvent.click(screen.getByRole('link', { name: 'Call overview' }))
    await screen.findByRole('heading', { name: 'Call C1042' })
  })

  it.each([
    { path: '/agent/conversations', heading: 'My conversations', list: true },
    { path: callPath, heading: 'Call C1042', list: false },
    { path: findingPath, heading: 'Procedure finding', list: false },
  ])('recovers from a failed request at $path through the visible retry action', async ({ path, heading, list }) => {
    const call = await callFixture()
    const response = deferred<CallReview | Conversation[]>()
    const request = vi.fn().mockRejectedValueOnce(new Error('Internal API failure')).mockReturnValueOnce(response.promise)
    openApp({ path, conversationsApi: { listForAgent: request }, callApi: { ...createDevCallApi(), getCallForAgent: request } })
    await screen.findByRole('alert')
    expect(screen.queryByText('Internal API failure')).toBeNull()
    press('Try again')
    expect(screen.getByRole('status').textContent).toContain('Loading')
    if (list) expect(screen.getByRole<HTMLInputElement>('searchbox').disabled).toBe(true)
    await act(() => response.resolve(list ? [conversation] : call))
    await screen.findByRole('heading', { name: heading })
    expect(screen.queryByRole('alert')).toBeNull()
    expect(request).toHaveBeenCalledTimes(2)
    if (list) expect(screen.getByRole<HTMLInputElement>('searchbox').disabled).toBe(false)
  })

  it.each(['detail', 'list'] as const)('ignores abandoned %s results after navigation', async (kind) => {
    const previous = deferred<CallReview | Conversation[]>()
    const call = await callFixture({ summary: 'OLD-RESPONSE' })
    const read = vi.fn().mockReturnValueOnce(previous.promise)
      .mockResolvedValueOnce(kind === 'detail' ? null : [conversation])
    const { router } = openApp({
      path: kind === 'detail' ? callPath : '/agent/conversations',
      conversationsApi: { listForAgent: read },
      callApi: { ...createDevCallApi(), getCallForAgent: read },
    })
    await screen.findByRole('status')
    if (kind === 'detail') {
      await act(() => router.navigate('/agent/conversations/OTHER'))
      await screen.findByRole('heading', { name: 'Conversation unavailable' })
    } else {
      await act(() => router.navigate('/agent/knowledge'))
      await screen.findByRole('table', { name: 'Approved entries' })
      await act(() => router.navigate('/agent/conversations'))
      await screen.findByText('C1042')
    }
    await act(() => previous.resolve(kind === 'detail' ? call : [{ ...conversation, id: 'OLD-RESPONSE' }]))
    expect(screen.queryByText('OLD-RESPONSE')).toBeNull()
  })

  it('opens the explicitly linked reference and refuses an unrelated one', async () => {
    const call = await callFixture()
    call.references.push({ ...call.references[0], id: 'RP-02', title: 'Delivery procedure' })
    call.criteria[1].referenceId = 'RP-02'
    const { router } = openCall(call, callPath + '/transcript?reference=RP-02#approved-reference')
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('heading', { name: 'Delivery procedure' })).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    await act(() => router.navigate(callPath + '/transcript?reference=UNRELATED#approved-reference'))
    expect(within(screen.getByRole('dialog')).getByRole('heading', { name: 'Approved reference unavailable' })).toBeTruthy()
    expect(within(screen.getByRole('dialog')).queryByText('Delivery procedure')).toBeNull()
  })
})

const note = 'The customer was verified by chat before this call.'
const reason = 'Purchase was verified in chat before turn 8.'
const contextLabel = 'Context for this call'
const reasonLabel = 'Reason for review'
const area = (name: string) => screen.findByLabelText<HTMLTextAreaElement>(name)
const enter = async (name: string, value: string) => fireEvent.change(await area(name), { target: { value } })

it('saves Agent context once and keeps it after navigating without requesting review', async () => {
  const fixtures = createDevCallApi()
  const response = deferred<AgentContext>()
  const saveContext = vi.fn(async (...args: Parameters<typeof fixtures.saveContext>) => {
    await response.promise
    return fixtures.saveContext(...args)
  })
  const requestReview = vi.spyOn(fixtures, 'requestReview')
  const { router } = openApp({ path: findingPath, fixtures, callApi: { ...fixtures, saveContext } })
  await enter(contextLabel, note)
  press('Save context')
  press('Saving…')
  expect(saveContext).toHaveBeenCalledExactlyOnceWith(agent.id, 'C1042', note)
  await act(() => response.resolve({ text: note, savedAt: '2026-10-29T15:00:00Z' }))
  await screen.findByText(/^Saved /)
  expect(requestReview).not.toHaveBeenCalled()
  await act(() => router.navigate(callPath))
  await act(() => router.navigate(findingPath))
  expect((await area(contextLabel)).value).toBe(note)
})

it.each([
  {
    method: 'saveContext', label: contextLabel, value: note, submit: 'Save context',
    error: 'Context could not be saved. Please try again.',
  },
  {
    method: 'requestReview', label: reasonLabel, value: reason, submit: 'Request review',
    error: 'The review request could not be sent. Please try again.',
  },
] as const)('retains input and allows retry after $method fails', async ({ method, label, value, submit, error }) => {
  const mock = vi.fn().mockRejectedValue(new Error('Offline'))
  openApp({ path: findingPath, callApi: { ...createDevCallApi(), [method]: mock } })
  await enter(label, value)
  press(submit)
  await screen.findByText(error)
  expect((await area(label)).value).toBe(value)
  expect(button(submit).disabled).toBe(false)
  expect(screen.queryByText(/^Saved /)).toBeNull()
})

it('saves a single review request and restores it in the queue and finding', async () => {
  const fixtures = createDevCallApi()
  const original = fixtures.requestReview
  const pending = deferred<void>()
  const requestReview = vi.fn(async (...args: Parameters<typeof original>) => {
    await pending.promise
    return original(...args)
  })
  fixtures.requestReview = requestReview
  const { router } = openApp({ path: findingPath, fixtures })
  await area(reasonLabel)
  expect(button('Request review').disabled).toBe(true)
  await enter(reasonLabel, reason)
  press('Request review')
  press('Sending…')
  expect(requestReview).toHaveBeenCalledExactlyOnceWith(agent.id, 'C1042', 'procedure-order', reason)
  await act(() => pending.resolve())
  await within(await screen.findByRole('region', { name: 'Flag feedback' })).findByText('Review requested')
  expect(screen.getByText(`Reason: ${reason}`)).toBeTruthy()
  await act(() => router.navigate('/agent/conversations'))
  expect(within((await screen.findByText('C1042')).closest('tr')!).getByText('Review requested')).toBeTruthy()
  await act(() => router.navigate(findingPath))
  await within(await screen.findByRole('region', { name: 'Flag feedback' })).findByText('Review requested')
  expect(screen.queryByLabelText(reasonLabel)).toBeNull()
})
