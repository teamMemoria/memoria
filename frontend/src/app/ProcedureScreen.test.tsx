import { it, expect } from 'vitest'
import { act, fireEvent, screen, within, assessmentData, openCategory, scoredCall, path } from './AssessmentTestSupport'
it('uses the exact selected reference and preserves source versions', async () => {
    const { call } = await openCategory()
    const reference = call.references[0]
    fireEvent.click(
      screen.getByRole('button', { name: `Reference ${reference.id}` }),
    )
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByText(`${reference.id} ${reference.version}`),
    ).toBeTruthy()
    expect(within(dialog).getByText(reference.title)).toBeTruthy()
  })

it('draws the stored percentage, keeps critical deductions visible and does not recalculate from check counts', async () => {
    const call = await scoredCall('procedure')
    const snapshot = JSON.stringify(call)
    await openCategory('procedure', call)
    expect(screen.getByText('75%')).toBeTruthy()
    expect(
      document.querySelector('.gauge-value')?.getAttribute('stroke-dasharray'),
    ).toBe('75 100')
    expect(screen.getByText('Evidence coverage: 50%')).toBeTruthy()
    expect(screen.getByText('4 / 8')).toBeTruthy()
    expect(document.querySelector('.critical-check')?.textContent).toContain(
      'Confirm the required input',
    )
    expect(document.querySelector('.metric-content--attention')).toBeTruthy()
    expect(screen.queryByText('Calculation and evidence')).toBeNull()
    expect(JSON.stringify(call)).toBe(snapshot)
  })

it('maps canonical check turns even when legacy evidence links are empty', async () => {
    const call = await scoredCall('procedure')
    const data = assessmentData(call, 'procedure')
    expect(data.turns.map((turn) => turn.number)).toEqual([8])
    await openCategory('procedure', call)
    fireEvent.click(screen.getByRole('button', { name: 'Compare evidence' }))
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByText('Verify the required input before continuing.'),
    ).toBeTruthy()
    expect(dialog.textContent).toContain('rule-v2')
    expect(dialog.textContent).toContain('transcript-v1')
    expect(
      within(dialog).getAllByText(
        call.transcript!.turns.find((turn) => turn.number === 8)!.text,
      ).length,
    ).toBeGreaterThan(0)
  })

it('opens the original check row with its exact evidence and rejects an unrelated check URL', async () => {
    const call = await scoredCall('procedure')
    const { router } = await openCategory('procedure', call)
    fireEvent.click(
      screen.getByRole('button', {
        name: /Critical · Confirm the required input/,
      }),
    )
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('rule-v2')
    expect(dialog.textContent).toContain(
      'Verify the required input before continuing.',
    )
    await act(() =>
      router.navigate(path + 'procedure?check=other-category-check'),
    )
    expect(
      await screen.findByText('Selected check unavailable for this category.'),
    ).toBeTruthy()
    expect(screen.queryByText('rule-v2', { exact: true })).toBeNull()
  })

it('shows transcript context before the check and keeps exact source versions expandable', async () => {
    const call = await scoredCall('procedure')
    await openCategory('procedure', call)
    fireEvent.click(screen.getByRole('button', { name: 'Compare evidence' }))
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getAllByRole('heading', {
        name: 'Confirm the required input',
      }),
    ).toHaveLength(1)
    const thread = dialog.querySelector('.evidence-thread')!
    const details = dialog.querySelector('.selected-check')!
    expect(
      thread.compareDocumentPosition(details) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    const provenance = within(dialog)
      .getByText('Source version')
      .closest('details')!
    expect(provenance.open).toBe(false)
    fireEvent.click(within(provenance).getByText('Source version'))
    expect(provenance.open).toBe(true)
    expect(provenance.textContent).toContain('transcript-v1')
    expect(dialog.textContent).toContain(
      'Verify the required input before continuing.',
    )
  })

it('shows a processing failure as an error without a filled performance gauge', async () => {
    const call = await scoredCall('completeness')
    call.criteria[0].scoring!.processingError = 'Source version unavailable'
    call.criteria[0].scoring!.score = null
    await openCategory('completeness', call)
    expect(screen.getByRole('alert').textContent).toContain(
      'This is not an Agent performance result',
    )
    expect(document.querySelector('.gauge-value')).toBeNull()
    expect(screen.queryByText('0%')).toBeNull()
    expect(screen.getByRole('img', { name: 'Processing error' })).toBeTruthy()
  })
