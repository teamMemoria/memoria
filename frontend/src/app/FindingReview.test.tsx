import { act, fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { createDevTeamReviewApi } from '../features/review-queue/devTeamReviewApi'
import type { TeamReviewApi } from '../features/review-queue/teamQueue'
import { agent, createDevCallApi, manager, openApp } from './TestSetup'

const asManager = { getViewer: async () => manager }
const lampPath = '/manager/conversations/C1051/findings/answer-support'
const decisionPanel = () => screen.getByRole('region', { name: 'Manager decision' })
const save = () => screen.getByRole<HTMLButtonElement>('button', { name: 'Save decision' })

function fillDecision(outcome: string) {
  fireEvent.click(screen.getByRole('radio', { name: new RegExp(`^${outcome}`) }))
  fireEvent.change(screen.getByLabelText('Reason for this decision'), { target: { value: 'Stock check is in the order log.' } })
  fireEvent.change(screen.getByLabelText('Feedback for the agent'), { target: { value: 'Say the stock check aloud next time.' } })
}

function openLamp(teamReviewApi?: TeamReviewApi) {
  const callApi = createDevCallApi()
  const view = openApp({
    path: lampPath,
    viewerApi: asManager,
    callApi,
    teamReviewApi: teamReviewApi ?? createDevTeamReviewApi(callApi),
  })
  return { callApi, ...view }
}

describe('Manager decisions on flagged feedback', () => {
  it('shows the transcript, approved reference, agent input and the original assessment separately', async () => {
    openApp({ path: '/manager/conversations/C1058/findings/completeness', viewerApi: asManager })
    await screen.findByRole('heading', { name: 'Refund timeline not confirmed with the customer.', level: 1 })
    const transcript = screen.getByRole('region', { name: 'Transcript' })
    expect(within(transcript).getByText('It can take 5 to 10 business days to reach your card.')).toBeTruthy()
    expect(within(transcript).getByText(/The recording ended before the call finished/)).toBeTruthy()
    const reference = screen.getByRole('region', { name: 'Approved reference' })
    expect(within(reference).getByText('RP-01 v1')).toBeTruthy()
    const input = screen.getByRole('region', { name: 'Agent input' })
    expect(within(input).getByText('The customer confirmed the timeline after the transcript cut off.')).toBeTruthy()
    expect(within(input).getByText('The agent did not add context.')).toBeTruthy()
    const original = screen.getByRole('region', { name: 'Automatic assessment' })
    expect(within(original).getByText('Suggested next step: Confirm the customer understands the refund timeline.')).toBeTruthy()
  })

  it('offers every outcome including Cannot assess and requires a reason and feedback', async () => {
    openLamp()
    await screen.findByRole('radio', { name: /^Cannot assess/ })
    expect(screen.getAllByRole('radio').map((radio) => radio.closest('label')!.querySelector('strong')!.textContent))
      .toEqual(['Confirmed', 'Corrected', 'Dismissed', 'Cannot assess'])
    expect(within(screen.getByRole('region', { name: 'Agent input' }))
      .getByText('I checked stock on the order screen while the customer was talking.')).toBeTruthy()
    expect(save().disabled).toBe(true)
    fireEvent.click(screen.getByRole('radio', { name: /^Cannot assess/ }))
    fireEvent.change(screen.getByLabelText('Reason for this decision'), { target: { value: 'Log unavailable.' } })
    expect(save().disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Feedback for the agent'), { target: { value: 'No action needed.' } })
    expect(save().disabled).toBe(false)
  })

  it('saves a decision that survives navigation, completes the review and keeps the original assessment', async () => {
    const { router } = openLamp()
    await screen.findByRole('radio', { name: /^Dismissed/ })
    fillDecision('Dismissed')
    fireEvent.click(save())
    await within(decisionPanel()).findByText('Dismissed')
    expect(within(decisionPanel()).getByText('Say the stock check aloud next time.')).toBeTruthy()
    expect(within(decisionPanel()).getByText('Maya Chen')).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Automatic assessment' })).toBeTruthy()
    await act(() => router.navigate('/manager/conversations?status=review-complete'))
    await screen.findByRole('link', { name: /^Review C1051/ })
    await act(() => router.navigate(lampPath))
    expect(await screen.findByText('Stock check is in the order log.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Save decision' })).toBeNull()
  })

  it('lets the Agent read the decision and feedback on their call', async () => {
    const callApi = createDevCallApi()
    await callApi.requestReview(agent.id, 'C1042', 'procedure-order', 'Purchase was verified in chat.')
    const teamReviewApi = createDevTeamReviewApi(callApi)
    const managerView = openApp({
      path: '/manager/conversations/C1042/findings/procedure-order',
      viewerApi: asManager, callApi, teamReviewApi,
    })
    await screen.findByRole('radio', { name: /^Corrected/ })
    fillDecision('Corrected')
    fireEvent.click(save())
    await within(decisionPanel()).findByText('Corrected')
    managerView.unmount()
    openApp({ path: '/agent/conversations/C1042', callApi, teamReviewApi })
    const decision = await screen.findByRole('region', { name: 'Manager decision' })
    expect(within(decision).getByText('Corrected')).toBeTruthy()
    expect(within(decision).getByText('Say the stock check aloud next time.')).toBeTruthy()
  })

  it('only lets authorized Managers save, in the page and in the development API', async () => {
    const callApi = createDevCallApi()
    const allowed = createDevTeamReviewApi(callApi)
    openLamp({
      ...allowed,
      getCallForManager: async (managerId, conversationId) => {
        const detail = await allowed.getCallForManager(managerId, conversationId)
        return detail && { ...detail, canDecide: false }
      },
    })
    await screen.findByText('You do not have permission to save review decisions.')
    expect(screen.queryByRole('button', { name: 'Save decision' })).toBeNull()
    const decision = { outcome: 'confirmed' as const, reason: 'r', feedback: 'f' }
    await expect(allowed.saveDecision(agent.id, 'C1051', 'answer-support', decision)).rejects.toThrow()
    await expect(allowed.saveDecision(manager.id, 'C1051', 'wrong-finding', decision)).rejects.toThrow()
  })

  it('does not show a failed save as successful and keeps the form', async () => {
    const callApi = createDevCallApi()
    const saveDecision = vi.fn().mockRejectedValue(new Error('Offline'))
    openLamp({ ...createDevTeamReviewApi(callApi), saveDecision })
    await screen.findByRole('radio', { name: /^Confirmed/ })
    fillDecision('Confirmed')
    fireEvent.click(save())
    expect((await screen.findByRole('alert')).textContent).toBe('The decision could not be saved. Please try again.')
    expect(screen.getByRole<HTMLInputElement>('radio', { name: /^Confirmed/ }).checked).toBe(true)
    expect(screen.getByLabelText<HTMLTextAreaElement>('Feedback for the agent').value).toBe('Say the stock check aloud next time.')
    expect(save().disabled).toBe(false)
    expect(within(decisionPanel()).queryByText('Maya Chen')).toBeNull()
    expect((await callApi.getCall('C1051'))?.decision).toBeNull()
  })

  it('shows an existing decision without the form', async () => {
    openApp({ path: '/manager/conversations/C1060/findings/procedure-order', viewerApi: asManager })
    await within(await screen.findByRole('region', { name: 'Manager decision' })).findByText('Dismissed')
    expect(screen.getByText('The order system log shows tracking was checked first.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Save decision' })).toBeNull()
  })
})
