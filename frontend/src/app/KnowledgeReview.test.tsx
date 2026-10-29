import { act, fireEvent, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { createDevApprovedKnowledgeApi } from '../lib/devApprovedKnowledge'
import { createDevKnowledgeReviewApi } from '../lib/devKnowledgeReview'
import type { KnowledgeReviewApi } from '../types/knowledge'
import { agent, manager, openApp } from './TestSetup'

const asManager = { getViewer: async () => manager }
const reviewPath = (id: string) => `/manager/knowledge/${id}`
const approve = () => screen.getByRole<HTMLButtonElement>('button', { name: 'Approve' })
const checkbox = () => screen.getByRole<HTMLInputElement>('checkbox')
const openReference = () => fireEvent.click(screen.getByRole('link', { name: /Open verification reference/ }))

function openReview(id: string, knowledgeReviewApi: KnowledgeReviewApi = createDevKnowledgeReviewApi()) {
  return openApp({ path: reviewPath(id), viewerApi: asManager, knowledgeReviewApi })
}

describe('Manager knowledge verification and approval', () => {
  it('shows the draft, its supporting passages and the verification reference', async () => {
    openReview('KD-103')
    await screen.findByRole('heading', { name: 'Refund timing for card payments', level: 1 })
    const draft = screen.getByRole('region', { name: 'Draft' })
    expect(within(draft).getByText('Card refunds usually appear within 5–10 business days.')).toBeTruthy()
    const passages = screen.getByRole('region', { name: 'Supporting conversations' })
    expect(within(passages).getByText('Call C1058')).toBeTruthy()
    expect(within(passages).getByText('Turn 11')).toBeTruthy()
    expect(within(passages).getByText('It can take 5 to 10 business days to reach your card.')).toBeTruthy()
    const link = screen.getByRole('link', { name: /Open verification reference: Card refund policy RF-04 v2/ })
    expect(link.getAttribute('href')).toBe('https://example.test/policies/RF-04')
  })

  it('does not unlock approval with permission alone', async () => {
    openReview('KD-103')
    await screen.findByRole('region', { name: 'Decision' })
    expect(approve().disabled).toBe(true)
    expect(checkbox().disabled).toBe(true)
    openReference()
    expect(approve().disabled).toBe(true)
    fireEvent.click(checkbox())
    expect(approve().disabled).toBe(false)
  })

  it('does not treat repeated answers as verification when no reference exists', async () => {
    const reviewApi = createDevKnowledgeReviewApi()
    openReview('KD-104', reviewApi)
    await screen.findByText(/Found in 3 conversations/)
    expect(screen.getByText(/No authoritative reference is available/)).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(approve().disabled).toBe(true)
    await expect(reviewApi.approve(manager.id, 'KD-104', '')).rejects.toThrow()
  })

  it('hides decisions from a Manager without knowledge permission', async () => {
    const reviewApi = createDevKnowledgeReviewApi()
    openReview('KD-103', {
      ...reviewApi,
      getForManager: async (managerId, entryId) => {
        const detail = await reviewApi.getForManager(managerId, entryId)
        return detail && { ...detail, canDecide: false }
      },
    })
    await screen.findByText('You do not have permission to approve or reject knowledge.')
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull()
  })

  it('approves a verified entry, shows the outcome and makes it available to Agents', async () => {
    const reviewApi = createDevKnowledgeReviewApi()
    const knowledgeApi = createDevApprovedKnowledgeApi(reviewApi)
    const { router } = openApp({ path: reviewPath('KD-103'), viewerApi: asManager, knowledgeReviewApi: reviewApi, knowledgeApi })
    await screen.findByRole('region', { name: 'Decision' })
    openReference()
    fireEvent.click(checkbox())
    fireEvent.click(approve())
    const decision = screen.getByRole('region', { name: 'Decision' })
    await within(decision).findByText('Approved')
    expect(within(decision).getByText('Maya Chen')).toBeTruthy()
    expect(within(decision).getByText('This entry is available on Agent knowledge pages.')).toBeTruthy()
    fireEvent.click(screen.getByRole('link', { name: 'Knowledge drafts' }))
    await screen.findByRole('tab', { name: 'Approved (2)' })
    expect(screen.getByRole('tab', { name: 'Pending (2)' })).toBeTruthy()
    expect(await knowledgeApi.getForAgent(agent.id, 'KD-103')).toMatchObject({ status: 'approved', approvedBy: 'Maya Chen' })
    await act(() => router.navigate('/manager/knowledge?tab=approved'))
    expect(screen.getByRole('link', { name: 'Refund timing for card payments' })).toBeTruthy()
  })

  it('requires a reason to reject and moves the entry to the Rejected queue', async () => {
    openReview('KD-102')
    const reject = await screen.findByRole<HTMLButtonElement>('button', { name: 'Reject' })
    expect(reject.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Reason for rejection'), { target: { value: 'Superseded by DL-03.' } })
    fireEvent.click(reject)
    const decision = screen.getByRole('region', { name: 'Decision' })
    await within(decision).findByText('Rejected')
    expect(within(decision).getByText('Reason: Superseded by DL-03.')).toBeTruthy()
    fireEvent.click(screen.getByRole('link', { name: 'Knowledge drafts' }))
    fireEvent.click(await screen.findByRole('tab', { name: 'Rejected (2)' }))
    expect(screen.getByRole('link', { name: 'Missing parcel claims' })).toBeTruthy()
  })

  it('keeps the form and shows an error when a decision fails to save', async () => {
    const reviewApi = createDevKnowledgeReviewApi()
    openReview('KD-103', {
      ...reviewApi,
      approve: vi.fn().mockRejectedValue(new Error('Offline')),
      reject: vi.fn().mockRejectedValue(new Error('Offline')),
    })
    await screen.findByRole('region', { name: 'Decision' })
    openReference()
    fireEvent.click(checkbox())
    fireEvent.change(screen.getByLabelText('Reason for rejection'), { target: { value: 'Draft reason' } })
    fireEvent.click(approve())
    expect((await screen.findByRole('alert')).textContent).toBe('The decision could not be saved. Please try again.')
    expect(checkbox().checked).toBe(true)
    expect(approve().disabled).toBe(false)
    expect(screen.getByLabelText<HTMLTextAreaElement>('Reason for rejection').value).toBe('Draft reason')
    expect(screen.queryByText('This entry is available on Agent knowledge pages.')).toBeNull()
  })

  it('shows the saved outcome for an entry that was already decided', async () => {
    openReview('KD-095')
    const decision = await screen.findByRole('region', { name: 'Decision' })
    expect(within(decision).getByText('Reason: Policy requires proof of purchase.')).toBeTruthy()
    expect(within(decision).queryByRole('button')).toBeNull()
  })
})
