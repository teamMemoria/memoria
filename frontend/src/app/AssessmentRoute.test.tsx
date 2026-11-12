import { it, expect } from 'vitest'
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
  callFixture,
  createDevCallApi,
  deferred,
  manager,
  openApp,
  assessmentData,
  categories,
  openCategory,
  path,
  vi,
} from './AssessmentTestSupport'
import type { CallReview } from './AssessmentTestSupport'
it.each(categories)(
  'renders $id from API data without synthetic scores',
  async ({ id, title }) => {
    const base = await callFixture()
    const criterion = base.criteria.find((item) => item.id === id)!
    await openCategory(id, {
      date: null,
      duration: null,
      criteria: [
        {
          ...criterion,
          explanation: 'Recorded assessment from API.',
          evidenceTurnNumbers: [2],
        },
      ],
      findings: [],
    })
    expect(screen.getByRole('heading', { name: title, level: 1 })).toBeTruthy()
    expect(screen.getByText('Recorded assessment from API.')).toBeTruthy()
    expect(screen.getByText('Score unavailable')).toBeTruthy()
    expect(
      within(screen.getByRole('list', { name: 'Call details' })).getByText(
        `${base.transcript!.turns.length} turns`,
      ),
    ).toBeTruthy()
    expect(screen.queryByText('Date not recorded')).toBeNull()
    expect(screen.queryByText('Duration not recorded')).toBeNull()
    expect(screen.queryByText('83 seconds before')).toBeNull()
    expect(screen.queryByText('2 requests')).toBeNull()
    expect(document.querySelector('audio')).toBeNull()
  },
)

it('opens every category from overview and preserves filters and history', async () => {
  const { router } = openApp({
    path: '/agent/conversations/C1042?q=refund&status=all',
  })
  await screen.findByRole('link', { name: /^Completeness:/ })
  const link = screen.getByRole('link', { name: /^Completeness:/ })
  fireEvent.click(link)
  await screen.findByRole('heading', { name: 'Completeness', level: 1 })
  expect(router.state.location.search).toBe('?q=refund&status=all')
  fireEvent.click(screen.getByRole('link', { name: /Answer support/ }))
  await screen.findByRole('heading', { name: 'Answer support', level: 1 })
  await act(() => router.navigate(-1))
  await screen.findByRole('heading', { name: 'Completeness', level: 1 })
  await act(() => router.navigate(1))
  await screen.findByRole('heading', { name: 'Answer support', level: 1 })
})

it('loads direct evidence, preserves exact text and hides unapproved references', async () => {
  const call = await callFixture()
  const original = call.references[0]
  call.references = [
    { ...original, status: 'draft', paragraphs: ['PRIVATE DRAFT'] },
  ]
  openApp({
    path: `${path}procedure?evidence=8,999&reference=${original.id}&section=2`,
    callApi: { ...createDevCallApi(), getCallForAgent: async () => call },
  })
  const dialog = await screen.findByRole('dialog')
  expect(
    within(dialog).getByText(
      call.transcript!.turns.find((turn) => turn.number === 8)!.text,
    ),
  ).toBeTruthy()
  expect(
    within(dialog).getByText('Selected passages unavailable: 999.'),
  ).toBeTruthy()
  expect(
    within(dialog).getByText(
      'No approved reference available for this selection.',
    ),
  ).toBeTruthy()
  expect(screen.queryByText('PRIVATE DRAFT')).toBeNull()
  fireEvent.click(
    within(dialog).getByRole('button', { name: 'Full transcript' }),
  )
  expect(
    await screen.findByRole('heading', { name: 'Full transcript' }),
  ).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Back to assessment' }))
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('does not label another category reference as applicable through a direct URL', async () => {
  const call = await callFixture()
  const reference = call.references[0]
  call.criteria = call.criteria.map((criterion) => ({
    ...criterion,
    referenceId: criterion.id === 'procedure' ? reference.id : null,
  }))
  call.findings = call.findings.filter(
    (finding) => finding.criterionId === 'procedure',
  )
  openApp({
    path: `${path}answer-support?reference=${reference.id}`,
    callApi: { ...createDevCallApi(), getCallForAgent: async () => call },
  })
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).queryByText(reference.title)).toBeNull()
  expect(
    within(dialog).getByText(
      'No approved reference available for this selection.',
    ),
  ).toBeTruthy()
})

it('handles loading, retry and processing without fabricated performance', async () => {
  const pending = deferred<CallReview | null>()
  const getCallForAgent = vi
    .fn()
    .mockReturnValueOnce(pending.promise)
    .mockResolvedValueOnce(
      await callFixture({ status: 'processing', criteria: [], findings: [] }),
    )
  openApp({
    path: path + 'completeness',
    callApi: { ...createDevCallApi(), getCallForAgent },
  })
  await screen.findByText('Loading assessment…')
  await waitFor(() => expect(getCallForAgent).toHaveBeenCalled())
  await act(() => pending.reject(new Error('private diagnostic')))
  await screen.findByRole('heading', { name: 'Unable to load assessment' })
  expect(screen.queryByText('private diagnostic')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await screen.findByText('Assessment results are not ready.')
  expect(screen.queryByText('Score unavailable')).toBeNull()
})

it.each([{ agentId: 'someone-else' }, { id: 'another-call' }])(
  'rejects mismatched response ownership or identity: %j',
  async (overrides) => {
    const pending = deferred<CallReview | null>()
    const { router } = openApp({
      path: path + 'procedure',
      callApi: {
        ...createDevCallApi(),
        getCallForAgent: () => pending.promise,
      },
    })
    await screen.findByText('Loading assessment…')
    const other = await callFixture(overrides)
    await act(() => pending.resolve(other))
    await screen.findByText(
      'This conversation is not available in your workspace.',
    )
    await act(() =>
      router.navigate('/manager/conversations/C1042/assessments/procedure'),
    )
    await screen.findByRole('heading', {
      name: 'Page unavailable for your role',
    })
  },
)

it('discards stale calls when navigating while a response is pending', async () => {
  const pending = deferred<CallReview | null>()
  const first = await callFixture({ topic: 'Old response' })
  const next = await callFixture({
    id: 'next-call',
    topic: 'Current response',
  })
  const api = {
    ...createDevCallApi(),
    getCallForAgent: vi
      .fn()
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce(next),
  }
  const { router } = openApp({ path: path + 'procedure', callApi: api })
  await screen.findByText('Loading assessment…')
  await act(() =>
    router.navigate('/agent/conversations/next-call/assessments/procedure'),
  )
  await screen.findByRole('link', { name: 'Current response' })
  await act(() => pending.resolve(first))
  expect(screen.queryByRole('link', { name: 'Old response' })).toBeNull()
})

it('uses the Manager endpoint and keeps decisions on their existing route', async () => {
  const call = await callFixture()
  const getCallForManager = vi.fn(async () => ({ call, canDecide: false }))
  const getCallForAgent = vi.fn()
  const saveDecision = vi.fn()
  openApp({
    path: '/manager/conversations/C1042/assessments/procedure',
    viewerApi: { getViewer: async () => manager },
    callApi: { ...createDevCallApi(), getCallForAgent },
    teamReviewApi: {
      getCallForManager,
      listForManager: async () => [],
      saveDecision,
    },
  })
  await screen.findByRole('heading', { name: 'Procedure', level: 1 })
  expect(getCallForManager).toHaveBeenCalledWith(manager.id, 'C1042')
  expect(getCallForAgent).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('link', { name: /^Review decision:/ }))
  await screen.findByText(
    'You do not have permission to save review decisions.',
  )
  expect(saveDecision).not.toHaveBeenCalled()
})

it('does not turn absent or inaccessible evidence into findings', async () => {
  const call = await callFixture({ transcript: null, findings: [] })
  const data = assessmentData(call, 'procedure')
  expect(data.turns).toEqual([])
  expect(data.findings).toEqual([])
  expect(data.missingTurns.length).toBeGreaterThan(0)
  const entry = call.references[0]
  call.references = [{ ...entry, availableToAgentIds: ['other'] }]
  expect(assessmentData(call, 'procedure').references).toEqual([])
})

it('shows unavailable assessments without fabricated scores or feedback-ready state', async () => {
  await openCategory('procedure', {
    sourceId: 'source-example',
    status: 'unavailable',
    criteria: [],
    findings: [],
    reviewRequest: null,
    decision: null,
    date: null,
    duration: null,
  })
  expect(
    screen.getByRole('heading', { name: 'Assessment unavailable' }),
  ).toBeTruthy()
  expect(screen.getByText(/ABCD source-example/)).toBeTruthy()
  expect(screen.queryByText('Feedback ready', { exact: true })).toBeNull()
  expect(
    screen.queryByRole('heading', { name: 'Calculation and evidence' }),
  ).toBeNull()
})
