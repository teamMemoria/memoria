import { it, expect } from 'vitest'
import { fireEvent, screen, within, callFixture, assessmentData, openCategory, scoredCall } from './AssessmentTestSupport'
it('renders partial scores, coverage and request changes without inventing completion', async () => {
    const call = await callFixture()
    const criterion = call.criteria.find((row) => row.id === 'completeness')!
    await openCategory('completeness', {
      assessmentVersion: {
        asOf: '2026-11-09',
        rules: 'test-rules',
        transcript: 'test-version',
      },
      criteria: [
        {
          ...criterion,
          scoring: {
            score: 100,
            coverage: 25,
            earned: 1,
            assessable: 1,
            possible: 4,
            processingError: null,
            interpretationLimits: [],
            limitations: ['No successful transaction is established.'],
            checks: [
              {
                id: 'request-change',
                ruleId: 'request-link',
                requirement: 'Address the request',
                outcome: 'supported',
                earned: 1,
                maximum: 1,
                explanation: 'The request was withdrawn.',
                advice: 'Keep fulfilment separate.',
                critical: false,
                citations: [],
              },
            ],
          },
        },
      ],
      requestLinks: [
        {
          id: 'request-1',
          text: 'Please email the receipt.',
          state: 'withdrawn',
          requestTurns: [2],
          responseTurns: [8],
          limitations: ['An explicit withdrawal, not a completed email.'],
        },
      ],
    })
    expect(screen.getByText('100%')).toBeTruthy()
    expect(screen.getByText('Evidence coverage: 25%')).toBeTruthy()
    expect(screen.getAllByText('withdrawn').length).toBeGreaterThan(0)
    expect(screen.queryByText('Calculation and evidence')).toBeNull()
    fireEvent.click(
      screen.getByRole('button', { name: /Please email the receipt/ }),
    )
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByText(
        call.transcript!.turns.find((t) => t.number === 8)!.text,
      ),
    ).toBeTruthy()
  })

it('keeps every unresolved request check accessible without presenting it as a customer request', async () => {
    const call = await scoredCall('completeness')
    call.criteria[0].scoring!.checks.push({
      ...call.criteria[0].scoring!.checks[1],
      id: 'later-check',
      requirement: 'Observe the later response',
      explanation: 'Later evidence remains unresolved.',
    })
    await openCategory('completeness', call)
    const limitations = screen
      .getByText('2 unresolved checks')
      .closest('details')!
    expect(limitations.open).toBe(false)
    expect(document.querySelectorAll('.request-list > button')).toHaveLength(0)
    fireEvent.click(within(limitations).getByText('2 unresolved checks'))
    expect(within(limitations).getAllByRole('button')).toHaveLength(2)
    fireEvent.click(
      within(limitations).getByRole('button', {
        name: 'Observe the later response',
      }),
    )
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('Later evidence remains unresolved.')
    expect(document.querySelector('.promise-note--empty')).toBeTruthy()
    expect(document.querySelector('.coaching--empty')).toBeTruthy()
  })

it('retains changed, withdrawn and promised requests with their distinct contextual evidence', async () => {
    const call = await scoredCall('completeness')
    call.requestLinks = ['changed', 'withdrawn', 'promised'].map(
      (state, index) => ({
        id: `request-${index}`,
        text: `Authored ${state} request`,
        state,
        requestTurns: [2],
        responseTurns: [8, 13],
        limitations: ['Sending is not verified.'],
      }),
    )
    await openCategory('completeness', call)
    for (const state of ['changed', 'withdrawn', 'promised'])
      expect(
        screen.getAllByText(state, { exact: true }).length,
      ).toBeGreaterThan(0)
    expect(
      assessmentData(call, 'completeness').turns.map((turn) => turn.number),
    ).toEqual([2, 8, 13])
    fireEvent.click(
      screen.getByRole('button', { name: /Authored withdrawn request/ }),
    )
    const dialog = await screen.findByRole('dialog')
    for (const number of [8, 13])
      expect(
        within(dialog).getByText(
          call.transcript!.turns.find((turn) => turn.number === number)!.text,
        ),
      ).toBeTruthy()
    expect(screen.queryByText('Completed', { exact: true })).toBeNull()
    expect(
      screen.getByText('No supported records supplied for this chart.'),
    ).toBeTruthy()
    expect(document.querySelector('.critical-check')).toBeTruthy()
  })

it('opens archived evidence for a simulation check without saved review controls', async () => {
  const call = await scoredCall('completeness')
  call.assessmentSource = 'simulation'
  call.sourceId = '117'
  const check = call.criteria[0].scoring!.checks[0]
  check.ruleId = 'completeness.direct_response'
  check.outcome = 'partial'
  check.earned = 0.5
  check.critical = false
  const reference = check.citations.find((citation) => citation.kind === 'reference')!
  reference.origin = 'synthetic assumptions'
  const customer = call.transcript!.turns.find((turn) => turn.speaker === 'Customer')!
  const agent = check.citations.find((citation) => citation.kind === 'conversation')!
  check.citations.push(
    { ...agent, turn_id: customer.number, quote: customer.text },
    { ...agent, turn_id: 13, quote: 'A quotation absent from the cited turn.' },
  )

  await openCategory('completeness', call)
  expect(screen.queryByText('Simulation', { exact: true })).toBeNull()
  expect(screen.getByRole('img', { name: '75%' })).toBeTruthy()
  expect(screen.queryByText('No supported request links supplied.')).toBeNull()
  const timeline = screen.getByRole('group', { name: 'Cited passages by retained turn order' })
  expect(within(timeline).getAllByRole('button')).toHaveLength(2)
  expect(within(timeline).queryByRole('button', { name: /Chart point: turn 13,/ })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /Confirm the required input.*Partial credit/ }))
  const evidence = await screen.findByRole('dialog')
  expect(within(evidence).getAllByText(call.transcript!.turns[7].text).length).toBeGreaterThan(0)
  expect(within(evidence).getByText(/Synthetic assumption/)).toBeTruthy()
  expect(evidence.textContent).not.toContain('eligible at the recorded assessment date')
  expect(screen.queryByRole('region', { name: 'Review actions' })).toBeNull()
})
