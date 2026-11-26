import { it, expect } from 'vitest'
import { fireEvent, screen, within, inspect, openCategory, scoredCall } from './AssessmentTestSupport'

it('uses stored coverage and opens changed, withdrawn and promised requests without inferring completion', async () => {
  const call = await scoredCall('completeness')
  Object.assign(call.criteria[0].scoring!, { score: 100, coverage: 25 })
  call.requestLinks = ['changed', 'withdrawn', 'promised'].map((state) => ({
    id: state, text: `Example ${state} request`, state, requestTurns: [2], responseTurns: [8, 13],
    limitations: ['Sending is not verified.'],
  }))
  await openCategory('completeness', call)
  expect(screen.getByRole('img', { name: '100%' })).toBeTruthy()
  expect(screen.getByText('Evidence coverage: 25%')).toBeTruthy()
  expect(screen.getByText('Promised; completion is not established.')).toBeTruthy()
  expect(screen.getByText('No supported records supplied for this chart.')).toBeTruthy()
  const dialog = await inspect(/Example withdrawn request/)
  expect(dialog.getByText('Recorded request state: withdrawn')).toBeTruthy()
  for (const number of [8, 13]) {
    const text = call.transcript!.turns.find((turn) => turn.number === number)!.text
    expect(dialog.getByText(text, { selector: '.evidence-thread blockquote' })).toBeTruthy()
  }
})

it('keeps unresolved checks available without treating them as customer requests', async () => {
  const call = await scoredCall('completeness')
  const checks = call.criteria[0].scoring!.checks
  checks.push({ ...checks[1], id: 'later', requirement: 'Observe the later response', explanation: 'Later evidence remains unresolved.' })
  await openCategory('completeness', call)
  const toggle = screen.getByText('2 unresolved checks')
  expect(toggle.closest('details')?.open).toBe(false)
  expect(document.querySelectorAll('.request-list > button')).toHaveLength(0)
  fireEvent.click(toggle)
  expect((await inspect('Observe the later response')).getByText('Later evidence remains unresolved.')).toBeTruthy()
})

it('filters archived chart links to exact citations and keeps the demo read-only', async () => {
  const call = await scoredCall('completeness')
  call.assessmentSource = 'simulation'
  call.sourceId = '7388'
  const check = call.criteria[0].scoring!.checks[0]
  Object.assign(check, { ruleId: 'completeness.direct_response', outcome: 'partial', earned: 0.5, critical: false })
  const reference = check.citations.find((citation) => citation.kind === 'reference')!
  reference.origin = 'synthetic assumptions'
  const customer = call.transcript!.turns.find((turn) => turn.speaker === 'Customer')!
  const agent = check.citations.find((citation) => citation.kind === 'conversation')!
  check.citations.push({ ...agent, turn_id: customer.number, quote: customer.text },
    { ...agent, turn_id: 13, quote: 'A quotation absent from the cited turn.' })

  await openCategory('completeness', call)
  const timeline = within(screen.getByRole('group', { name: 'Cited passages by retained turn order' }))
  expect(timeline.getAllByRole('button')).toHaveLength(2)
  expect(timeline.queryByRole('button', { name: /Chart point: turn 13,/ })).toBeNull()
  const dialog = await inspect(/Confirm the required input.*Partial credit/)
  expect(dialog.getByText('Completeness · Call ABCD 7388')).toBeTruthy()
  expect(dialog.getByText(reference.quote).closest('details')?.open).toBe(false)
  expect(dialog.queryByRole('button', { name: /^Turn 13/ })).toBeNull()
  expect(dialog.queryByText(/Synthetic assumption/)).toBeNull()
  expect(dialog.queryByText(`Reference ${reference.reference_id}`)).toBeNull()
  expect(dialog.queryByText('Source version')).toBeNull()
  expect(dialog.queryByText('Agent statements do not verify system actions.')).toBeNull()
  expect(dialog.queryByText('Eligible at the recorded assessment date')).toBeNull()
  expect(screen.queryByRole('region', { name: 'Review actions' })).toBeNull()
})
