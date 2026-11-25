import { it, expect } from 'vitest'
import { act, screen, within, assessmentData, inspect, openCategory, scoredCall, path } from './AssessmentTestSupport'

it('opens the applicable reference with its exact version', async () => {
  const { call } = await openCategory()
  const reference = call.references[0]
  const dialog = await inspect(`Reference ${reference.id}`)
  expect(dialog.getByText(`${reference.id} ${reference.version}`)).toBeTruthy()
  expect(dialog.getByText(reference.title)).toBeTruthy()
})

it('renders the recorded score and compares a critical finding with exact cited evidence', async () => {
  const call = await scoredCall('procedure')
  const original = structuredClone(call)
  const { turns } = assessmentData(call, 'procedure')
  expect(turns.map((turn) => turn.number)).toEqual([8])
  await openCategory('procedure', call)
  expect(screen.getByRole('img', { name: '75%' })).toBeTruthy()
  expect(document.querySelector('.gauge-value')?.getAttribute('stroke-dasharray')).toBe('75 100')
  expect(screen.getByText('Evidence coverage: 50%')).toBeTruthy()

  const finding = within(document.querySelector<HTMLElement>('.finding-card')!)
  expect(finding.getByText('Deduction')).toBeTruthy()
  expect(finding.getByText(turns[0].text)).toBeTruthy()
  expect(finding.getByRole('button', { name: 'View turn 8' })).toBeTruthy()
  const dialog = await inspect('Compare evidence', finding)
  expect(dialog.getByText('Verify the required input before continuing.')).toBeTruthy()
  expect(dialog.queryByText('Version transcript-v1')).toBeNull()
  expect(dialog.getByText('Version rule-v2')).toBeTruthy()
  const evidence = dialog.getByRole('heading', { name: 'Confirm the required input' })
  expect(dialog.getAllByText(turns[0].text)[0].compareDocumentPosition(evidence) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(dialog.getByText('Reference version and eligibility').closest('details')?.open).toBe(false)
  expect(call).toEqual(original)
})

it('keeps additional check URLs scoped to the selected assessment', async () => {
  const { router } = await openCategory('procedure', await scoredCall('procedure'))
  const dialog = await inspect(/Confirm the required input \(critical\)/)
  expect(dialog.getByText('Verify the required input before continuing.')).toBeTruthy()
  await act(() => router.navigate(path + 'procedure?check=other-category-check'))
  expect(await screen.findByText('Selected check unavailable for this category.')).toBeTruthy()
  expect(screen.queryByText('Version rule-v2')).toBeNull()
})

it('reports a processing error without showing a score', async () => {
  const call = await scoredCall('completeness')
  Object.assign(call.criteria[0].scoring!, { processingError: 'Source version unavailable', score: null })
  await openCategory('completeness', call)
  expect(screen.getByRole('alert').textContent).toContain('Source version unavailable')
  expect(screen.getByRole('img', { name: 'Processing error' })).toBeTruthy()
  expect(document.querySelector('.gauge-value')).toBeNull()
})
