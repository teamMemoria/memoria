import { expect, it, vi } from 'vitest'
import { act, fireEvent, screen, within } from '@testing-library/react'
import { openCategory, path, press } from './AssessmentTestSupport'
import { assessmentData, categories } from '../features/assessment-shared/assessment'
import { callFixture, createDevCallApi, manager, openApp, openCall } from './TestSetup'

it.each(categories)('opens the $id assessment from overview and renders stored evidence', async ({ title }) => {
  const call = await callFixture({ findings: [], date: null, duration: null })
  call.criteria = call.criteria.map((criterion) => ({
    ...criterion,
    explanation: 'Recorded assessment from API.',
    evidenceTurnNumbers: [2],
  }))
  const query = '?q=refund&status=all'
  const { router } = openCall(call, '/agent/conversations/C1042' + query)
  fireEvent.click(await screen.findByRole('link', { name: new RegExp(`^${title}:`) }))
  await screen.findByRole('heading', { name: title, level: 1 })
  expect(router.state.location.search).toBe(query)
  expect(screen.getByText('Recorded assessment from API.')).toBeTruthy()
  expect(screen.getByText('Score unavailable')).toBeTruthy()
  expect(within(screen.getByRole('list', { name: 'Call details' })).getByText(`${call.transcript!.turns.length} turns`)).toBeTruthy()
  await act(() => router.navigate(-1))
  await screen.findByRole('heading', { name: 'Call C1042', level: 1 })
  await act(() => router.navigate(1))
  await screen.findByRole('heading', { name: title, level: 1 })
})

it.each(['unapproved', 'other category'] as const)('shows exact deep-linked evidence and hides an %s reference', async (kind) => {
  const call = await callFixture()
  call.transcript!.turns = call.transcript!.turns.filter(({ number }) => number !== 9)
  const nextRecordedTurn = call.transcript!.turns.find(({ number }) => number === 10)!.text
  const entry = call.references[0]
  if (kind === 'unapproved') call.references = [{ ...entry, status: 'draft', paragraphs: ['PRIVATE DRAFT'] }]
  else call.criteria = call.criteria.map((criterion) => criterion.id === 'answer-support'
    ? { ...criterion, referenceId: null } : criterion)
  openCall(call, `${path}answer-support?evidence=8,999&reference=${entry.id}&section=2`)
  const dialog = within(await screen.findByRole('dialog'))
  expect(dialog.getByText(call.transcript!.turns.find(({ number }) => number === 8)!.text)).toBeTruthy()
  expect(dialog.getByText('Selected passages unavailable: 999.')).toBeTruthy()
  expect(dialog.getByText('No approved reference available for this selection.')).toBeTruthy()
  expect(dialog.queryByText(entry.title)).toBeNull()
  expect(dialog.queryByText('PRIVATE DRAFT')).toBeNull()
  expect(dialog.queryByText(nextRecordedTurn)).toBeNull()
  press('Surrounding turns', dialog)
  expect(dialog.getByText(nextRecordedTurn)).toBeTruthy()
  press('Full transcript', dialog)
  await dialog.findByRole('heading', { name: 'Full transcript' })
  press('Back to assessment')
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('handles loading, retry and processing without fabricated performance', async () => {
  const getCallForAgent = vi.fn()
    .mockRejectedValueOnce(new Error('private diagnostic'))
    .mockResolvedValueOnce(await callFixture({ status: 'processing', criteria: [], findings: [] }))
  openApp({ path: path + 'completeness', callApi: { ...createDevCallApi(), getCallForAgent } })
  await screen.findByRole('heading', { name: 'Unable to load assessment' })
  expect(screen.queryByText('private diagnostic')).toBeNull()
  press('Try again')
  await screen.findByText('Assessment results are not ready.')
  expect(screen.queryByText('Score unavailable')).toBeNull()
  expect(getCallForAgent).toHaveBeenCalledTimes(2)
})

it.each([
  ['partial', 'Assessment incomplete'],
  ['unavailable', 'Assessment unavailable'],
] as const)('keeps %s distinct from ready feedback', async (status, title) => {
  await openCategory('procedure', { status, findings: [], sourceId: 'source-example' })
  expect(screen.getByRole('heading', { name: title })).toBeTruthy()
  expect(within(screen.getByRole('list', { name: 'Call details' })).getByText(/ABCD source-example/)).toBeTruthy()
  expect(screen.queryByText('Feedback ready', { exact: true })).toBeNull()
  if (status === 'partial') expect(screen.getByText(/feedback is not ready/)).toBeTruthy()
  else expect(screen.queryByRole('navigation', { name: 'Assessment categories' })).not.toBeNull()
})

it('uses the Manager endpoint and keeps decisions on their existing route', async () => {
  const call = await callFixture()
  const getCallForManager = vi.fn(async () => ({ call, canDecide: false }))
  const getCallForAgent = vi.fn()
  const saveDecision = vi.fn()
  openApp({
    path: '/manager/conversations/C1042/assessments/procedure',
    as: manager,
    callApi: { ...createDevCallApi(), getCallForAgent },
    teamReviewApi: { getCallForManager, listForManager: async () => [], saveDecision },
  })
  fireEvent.click(await screen.findByRole('link', { name: /^Review decision:/ }))
  await screen.findByText('You do not have permission to save review decisions.')
  expect(getCallForManager).toHaveBeenCalledWith(manager.id, 'C1042')
  expect(getCallForAgent).not.toHaveBeenCalled()
  expect(saveDecision).not.toHaveBeenCalled()
})

it('does not turn absent or inaccessible evidence into findings', async () => {
  const call = await callFixture({ transcript: null, findings: [] })
  call.references = [{ ...call.references[0], availableToAgentIds: ['other'] }]
  const data = assessmentData(call, 'procedure')
  expect(data).toMatchObject({ turns: [], findings: [], references: [] })
  expect(data.missingTurns.length).toBeGreaterThan(0)
})

it('reports an unsupported category', async () => {
  openCall(await callFixture(), path + 'unknown')
  await screen.findByText('Unknown category.')
})
