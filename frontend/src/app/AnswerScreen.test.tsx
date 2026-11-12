import { it, expect } from 'vitest'
import { fireEvent, screen, within, openCategory, scoredCall } from './AssessmentTestSupport'
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
    const remaining = screen
      .getByText('1 unresolved · 0 not applicable')
      .closest('details')!
    expect(remaining.open).toBe(false)
    fireEvent.click(
      within(remaining).getByText('1 unresolved · 0 not applicable'),
    )
    fireEvent.click(
      within(remaining).getByRole('button', { name: 'View evidence' }),
    )
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
    expect(screen.getByText('recorded checks')).toBeTruthy()
    expect(screen.queryByText('statements', { exact: true })).toBeNull()
    expect(
      screen.getAllByText('Verify the required input before continuing.')
        .length,
    ).toBeGreaterThan(0)
    expect(screen.getByText('75%')).toBeTruthy()
  })
