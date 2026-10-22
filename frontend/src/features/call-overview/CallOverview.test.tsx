import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'
import type { CallApi, CallReview } from '../../types/callReview'
import type { Viewer } from '../../types/viewer'
import { agent, callFixture, deferred } from '../../lib/callReview.test-data'
import { CallOverview } from './CallOverview'

afterEach(cleanup)

function mount(
  api: CallApi | null,
  path = '/agent/conversations/C1042',
  viewer: Viewer = agent,
) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/agent/conversations/:conversationId"
          element={<CallOverview viewer={viewer} api={api} />}
        />
      </Routes>
    </MemoryRouter>,
  )
}

async function show(call: CallReview, path?: string) {
  const getCallForAgent = vi.fn(async () => call)
  mount({ getCallForAgent }, path)
  await screen.findByRole('heading', { name: call.topic })
  return getCallForAgent
}

describe('call overview', () => {
  it('shows metadata, summary and all four automated results without a Manager decision', async () => {
    const call = await callFixture()
    const getCallForAgent = await show(call)
    expect(getCallForAgent).toHaveBeenCalledWith(agent.id, call.id)
    const details = within(screen.getByRole('list', { name: 'Call details' }))
    expect(details.getByText(`Call ${call.id}`)).toBeTruthy()
    expect(details.getByText(agent.displayName)).toBeTruthy()
    expect(details.getByText('Oct 8, 2026')).toBeTruthy()
    expect(details.getByText('4 min 32 sec')).toBeTruthy()
    expect(screen.getByText(call.summary)).toBeTruthy()
    const audit = within(screen.getByRole('region', { name: 'Automatic feedback' }))
    expect(audit.getByRole('link', { name: 'Procedure: Needs review' })).toBeTruthy()
    for (const title of ['Answer support', 'Completeness', 'Communication style']) {
      expect(audit.getByLabelText(`${title}: Meets criteria`)).toBeTruthy()
    }
    expect(audit.getByText('Text only')).toBeTruthy()
    expect(screen.getByRole('heading', { name: '1 automated finding' })).toBeTruthy()
    expect(screen.queryByRole('region', { name: 'Manager decision' })).toBeNull()
  })

  it.each([
    ['confirmed', 'Confirmed'],
    ['corrected', 'Corrected'],
    ['dismissed', 'Dismissed'],
    ['cannot-assess', 'Cannot assess'],
  ] as const)('shows a %s Manager decision separately from the original assessment', async (outcome, label) => {
    const call = await callFixture({
      decision: {
        outcome,
        reason: 'The Manager reviewed the cited evidence.',
        feedback: 'Verify the purchase before offering a refund.',
        managerName: 'Maya Chen',
        decidedAt: '2026-10-09T14:00:00Z',
      },
    })
    await show(call)
    const decision = within(screen.getByRole('region', { name: 'Manager decision' }))
    expect(decision.getByText(label)).toBeTruthy()
    expect(decision.getByText(call.decision!.reason)).toBeTruthy()
    expect(decision.getByText(call.decision!.feedback)).toBeTruthy()
    expect(decision.getByText('Maya Chen')).toBeTruthy()
    expect(decision.getByText('Oct 9, 2026')).toBeTruthy()
    const audit = within(screen.getByRole('region', { name: 'Automatic feedback' }))
    expect(audit.getByRole('link', { name: 'Procedure: Needs review' })).toBeTruthy()
    expect(decision.queryByRole('button')).toBeNull()
  })

  it('shows processing feedback without displaying completed assessments', async () => {
    await show(await callFixture({ status: 'processing' }))
    expect(screen.getByRole('status').textContent).toContain('not ready')
    expect(screen.queryByRole('region', { name: 'Automatic feedback' })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Automated findings' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Transcript' }).getAttribute('href'))
      .toBe('/agent/conversations/C1042/transcript')
  })

  it('allows transcript access when there are no findings', async () => {
    const call = await callFixture({ findings: [] })
    call.criteria = call.criteria.map(criterion => ({
      ...criterion, result: 'meets-criteria', findingId: null,
    }))
    await show(call)
    expect(screen.queryByRole('region', { name: 'Automated findings' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'View feedback' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Transcript' })).toBeTruthy()
  })

  it('preserves a Cannot assess result as a separate categorical outcome', async () => {
    const call = await callFixture()
    call.criteria[1].result = 'cannot-assess'
    await show(call)
    const audit = within(screen.getByRole('region', { name: 'Automatic feedback' }))
    const criterion = within(audit.getByLabelText('Answer support: Cannot assess'))
    expect(criterion.getByText('Cannot assess')).toBeTruthy()
    expect(criterion.queryByText('Needs review')).toBeNull()
  })

  it('renders the loading announcement until the call arrives', async () => {
    const call = await callFixture()
    const pending = deferred<CallReview | null>()
    mount({ getCallForAgent: () => pending.promise })
    expect(screen.getByRole('status').textContent).toBe('Loading conversation…')
    expect(screen.queryByRole('region', { name: 'Automatic feedback' })).toBeNull()
    await act(async () => pending.resolve(call))
    expect(screen.getByRole('heading', { name: call.topic })).toBeTruthy()
    expect(screen.queryByRole('status')).toBeNull()
  })

  it.each([
    [null, 'Conversation data is not connected.'],
    [{ getCallForAgent: async () => null }, 'This conversation is not available in your workspace.'],
  ] as const)('explains unavailable call data without a misleading retry', async (api, message) => {
    mount(api)
    await screen.findByRole('heading', { name: 'Conversation unavailable' })
    expect(screen.getByText(message)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  })

  it('offers a working retry without exposing internal errors', async () => {
    const call = await callFixture()
    const pending = deferred<CallReview | null>()
    const getCallForAgent = vi.fn<CallApi['getCallForAgent']>()
      .mockRejectedValueOnce(new Error('Private API details'))
      .mockReturnValueOnce(pending.promise)
    mount({ getCallForAgent })
    await screen.findByRole('alert')
    expect(screen.queryByText('Private API details')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByRole('status').textContent).toBe('Loading conversation…')
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
    await act(async () => pending.resolve(call))
    expect(screen.getByRole('heading', { name: call.topic })).toBeTruthy()
    expect(getCallForAgent).toHaveBeenCalledTimes(2)
  })

  it('does not fetch Agent call data for a Manager', () => {
    const getCallForAgent = vi.fn<CallApi['getCallForAgent']>()
    mount({ getCallForAgent }, undefined, {
      id: 'manager-maya-chen', displayName: 'Maya Chen', role: 'manager',
    })
    expect(screen.getByRole('heading', { name: 'Page unavailable for your role' })).toBeTruthy()
    expect(getCallForAgent).not.toHaveBeenCalled()
    expect(screen.getByRole('link', { name: 'Back to your conversations' }).getAttribute('href'))
      .toBe('/manager/conversations')
  })

  it('keeps the call, finding, selected turn and list filters in its handoff links', async () => {
    await show(await callFixture(),
      '/agent/conversations/C1042?q=Refund&status=feedback-ready&turn=99')
    expect(screen.getByRole('link', { name: 'Conversations' }).getAttribute('href'))
      .toBe('/agent/conversations?q=Refund&status=feedback-ready')
    expect(screen.getByRole('link', { name: 'Procedure: Needs review' }).getAttribute('href'))
      .toBe('/agent/conversations/C1042/findings/procedure-order?q=Refund&status=feedback-ready&turn=8')
    expect(screen.getByRole('link', { name: 'View feedback' }).getAttribute('href'))
      .toBe('/agent/conversations/C1042/findings/procedure-order?q=Refund&status=feedback-ready')
    expect(screen.getByRole('link', { name: 'Transcript' }).getAttribute('href'))
      .toBe('/agent/conversations/C1042/transcript?q=Refund&status=feedback-ready')
  })

  it.skip('shows the Cannot assess explanation (pending the overview explanation UI)', async () => {
    const call = await callFixture()
    call.criteria[1] = {
      ...call.criteria[1],
      result: 'cannot-assess',
      explanation: 'No applicable approved reference was supplied.',
    }
    await show(call)
    expect(screen.getByText(call.criteria[1].explanation)).toBeTruthy()
  })
})
