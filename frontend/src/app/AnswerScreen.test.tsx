import { it, expect } from 'vitest'
import { fireEvent, screen, within, openCategory, scoredCall, path } from './AssessmentTestSupport'
import { openCall } from './TestSetup'

it.each([true, false])('only shows a follow-up with related recorded evidence, linked: %s', async (linked) => {
  const call = await scoredCall('answer-support')
  const [check, otherCheck] = call.criteria[0].scoring!.checks
  const originalCitation = check.citations.find((citation) => citation.kind === 'conversation')!
  const text = 'Thanks, it worked.'
  const assumption = 'Hypothetical unrecorded outcome.'
  const followUp = { ...originalCitation, turn_id: 100, quote: text }
  call.transcript!.turns.push({ number: 100, speaker: 'Customer', text, time: null })
  check.citations.push({
    kind: 'reference', origin: 'synthetic assumptions', quote: assumption,
    section_id: 'assumptions', reference_id: 'demo-assumptions', reference_version: 'v1',
  })
  otherCheck.ruleId = 'answer-support.recorded_outcomes'
  otherCheck.citations = linked ? [originalCitation, followUp] : [followUp]

  const { router } = openCall(call, `${path}answer-support?evidence=8&check=${check.id}`)
  const dialog = within(await screen.findByRole('dialog', { name: check.requirement }))
  expect(dialog.getByText('0/1 points')).toBeTruthy()
  expect(dialog.getByText(assumption).closest('details')?.open).toBe(false)
  expect(Boolean(dialog.queryByRole('heading', { name: 'Customer follow-up' }))).toBe(linked)
  if (linked) {
    fireEvent.click(dialog.getByRole('button', { name: /^Turn 100/ }))
    expect(router.state.location.search).toBe('?evidence=100')
    expect(dialog.getByText(text)).toBeTruthy()
  }
})

it('groups unresolved answer checks while retaining critical checks and selection-specific sources', async () => {
    const call = await scoredCall('answer-support')
    call.criteria[0].scoring!.checks.push({
      ...call.criteria[0].scoring!.checks[1],
      id: 'critical-unresolved',
      requirement: 'Critical unresolved requirement',
      critical: true,
    })
    const snapshot = JSON.stringify(call)
    await openCategory('answer-support', call)
    const primary = screen.getByRole('table', {
      name: 'Assessed and critical answer checks',
    })
    expect(primary.textContent).toContain('Critical unresolved requirement')
    expect(primary.textContent).not.toContain('Observe the purchase outcome')
    const toggle = screen.getByLabelText('Additional checks')
    const remaining = toggle.closest('details')!
    expect(screen.queryByText('1 unresolved, 0 not applicable')).toBeNull()
    expect(remaining.open).toBe(false)
    fireEvent.click(toggle)
    const evidence = within(remaining).getByRole('button', { name: 'View evidence' })
    expect(evidence.querySelector('.codicon')).toBeNull()
    fireEvent.click(evidence)
    expect((await screen.findByRole('dialog')).textContent).toContain(
      'Observe the purchase outcome',
    )
    expect(document.querySelector('.source-scope')?.textContent).toContain(
      'Observe the purchase outcome',
    )
    expect(document.querySelector('.score-area')?.textContent).toContain('75%')
    expect(JSON.stringify(call)).toBe(snapshot)
  })

it('uses recorded outcomes for the answer chart, never invented claim totals', async () => {
    const call = await scoredCall('answer-support')
    await openCategory('answer-support', call)
    expect(
      screen.getByRole('img', {
        name: 'Recorded checks: 0 supported, 1 deduction, 1 unresolved, 0 not applicable',
      }),
    ).toBeTruthy()
    expect(screen.getByText('checks', { exact: true })).toBeTruthy()
    expect(screen.queryByText('statements', { exact: true })).toBeNull()
    expect(
      screen.getAllByText('Verify the required input before continuing.')
        .length,
    ).toBeGreaterThan(0)
    expect(screen.getByText('75%')).toBeTruthy()
  })

it.each([false, true])('shows the latest cited system record for a recovery email claim, completion recorded: %s', async (completed) => {
  const call = await scoredCall('answer-support')
  const check = call.criteria[0].scoring!.checks[0]
  check.requirement = 'Ensure claims that the recovery email was sent match the recorded outcome'
  check.outcome = 'supported'
  check.explanation = 'The recovery link was sent.'

  const pendingAction = {
    kind: 'conversation',
    event_kind: 'action',
    conversation_id: 'authored-source',
    transcript_version: 'transcript-v1',
    turn_id: 100,
    quote: 'A link will be sent.',
  } as const
  const sentAction = { ...pendingAction, turn_id: 101, quote: 'Recovery link sent.' }
  const actions = completed ? [sentAction, pendingAction] : [pendingAction]
  for (const action of actions) {
    check.citations.push(action)
    call.transcript!.turns.push({ number: action.turn_id, speaker: 'System action', text: action.quote, time: null })
  }

  await openCategory('answer-support', call)
  expect(screen.getByRole('heading', { name: 'Recovery email claim' })).toBeTruthy()
  const source = screen.getByRole('button', { name: /^System record/ })
  expect(source.textContent).toContain(completed ? sentAction.quote : pendingAction.quote)
  expect(document.querySelector('.answer-check-summary')?.textContent).toBe(completed
    ? check.explanation
    : 'The cited system record describes a planned send. Completion is unverified.')
})
