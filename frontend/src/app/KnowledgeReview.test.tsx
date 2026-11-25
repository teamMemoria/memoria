import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { createDevApprovedKnowledgeApi } from '../test/devApprovedKnowledge'
import { createDevKnowledgeReviewApi } from '../test/devKnowledgeReview'
import type { KnowledgeDraft, KnowledgeReviewApi } from '../types/knowledge'
import { agent, button, deferred, input, manager, openApp, press } from './TestSetup'

const refund = 'KD-103'
const missingParcel = 'KD-102'
const promotion = 'KD-104'
const reviewPath = (id: string) => `/manager/knowledge/${id}`
const actions = () => within(screen.getByRole('region', { name: 'Decision' }))
const field = (name: string) => screen.getByLabelText<HTMLInputElement>(name)
function verify() {
  const trigger = button('Verify reference')
  if (trigger.getAttribute('aria-expanded') === 'false') fireEvent.click(trigger)
  fireEvent.click(screen.getByRole('link', { name: /Open verification reference/ }))
  expect(button('Approve').disabled).toBe(true)
  fireEvent.click(screen.getByRole('checkbox'))
}

function review(
  id = refund,
  overrides: Partial<KnowledgeReviewApi> = {},
  api = createDevKnowledgeReviewApi(),
) {
  const knowledgeApi = createDevApprovedKnowledgeApi(api)
  const app = openApp({
    path: reviewPath(id),
    as: manager,
    knowledgeReviewApi: { ...api, ...overrides },
    knowledgeApi,
  })
  return { ...app, api, knowledgeApi }
}

async function draftFixture(id: string, fields?: Partial<KnowledgeDraft>) {
  const api = createDevKnowledgeReviewApi()
  const detail = (await api.getForManager(manager.id, id))!
  return { ...detail.entry, ...fields }
}

it('previews edits below Sources and saves them against the displayed draft version', async () => {
  const entry = await draftFixture(refund, { layer: 'layer2', question: 'When do card refunds arrive?' })
  const title = 'Card refund timing'
  const guidance = 'Check the payment record.'
  const editDraft = vi.fn().mockResolvedValue({
    ...entry, title, version: 'new-version', paragraphs: [guidance], verificationReference: null,
  })
  review(entry.id, { editDraft, getForManager: async () => ({ entry, canDecide: true, canEdit: true }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Edit draft' }))
  input('Title', title)
  input('Guidance', guidance)
  expect(within(screen.getByRole('region', { name: 'Draft document viewer' })).getByText(title)).toBeTruthy()
  expect(button('Approve').disabled).toBe(true)
  press('Save draft')
  expect(editDraft).toHaveBeenCalledWith(manager.id, entry.id, {
    title, question: entry.question, guidance, version: entry.version,
  })
  await screen.findByRole('heading', { name: title, level: 1 })
  expect(screen.queryByRole('form', { name: 'Edit draft' })).toBeNull()
  expect(button('Approve').disabled).toBe(true)
})

it.each(['read-only API', 'restricted Manager'])('keeps the draft readable for a %s', async (access) => {
  const entry = await draftFixture(refund)
  const approve = vi.fn()
  const reject = vi.fn()
  review(refund, {
    approve, reject, decisionsAvailable: access !== 'read-only API',
    getForManager: async () => ({ entry, canDecide: access === 'read-only API' }),
  })
  const message = access === 'read-only API'
    ? /Knowledge drafts are read-only in this demo/
    : 'You do not have permission to approve or reject knowledge.'
  await screen.findByText(message)
  expect(screen.getByRole('region', { name: 'Knowledge entry' })).toBeTruthy()
  for (const name of ['Approve', 'Reject', 'Edit draft']) expect(screen.queryByRole('button', { name })).toBeNull()
  expect(approve).not.toHaveBeenCalled()
  expect(reject).not.toHaveBeenCalled()
})

it('shows cited passages and restores focus without crediting them as verification', async () => {
  review()
  const source = await screen.findByRole('button', { name: 'View source call C1058' })
  source.focus()
  fireEvent.click(source)
  const dialog = await screen.findByRole('dialog', { name: 'Call C1058' })
  expect(within(dialog).getByText('Turn 11')).toBeTruthy()
  expect(within(dialog).getByText('It can take 5 to 10 business days to reach your card.')).toBeTruthy()
  fireEvent.keyDown(dialog, { key: 'Escape' })
  await waitFor(() => expect(source).toBe(document.activeElement))
  expect(screen.queryByRole('dialog')).toBeNull()
  press('Verify reference')
  expect(screen.getByRole<HTMLInputElement>('checkbox').disabled).toBe(true)
  expect(button('Approve').disabled).toBe(true)
  expect(screen.getByRole('link', { name: /Open verification reference: Card refund policy RF-04 v2/ })
    .getAttribute('href')).toBe('https://example.test/policies/RF-04')
})

it('shows absent passages and refuses to treat multiple source calls as verification', async () => {
  const { api } = review(promotion, { attachVerification: vi.fn() })
  const sources = await screen.findByRole('region', { name: 'Sources' })
  expect(within(sources).getAllByRole('button', { name: /^View source call / })).toHaveLength(3)
  press('View source call C1042')
  const dialog = within(await screen.findByRole('dialog', { name: 'Call C1042' }))
  expect(dialog.getByText('No conversation passages are available for this source.')).toBeTruthy()
  fireEvent.click(dialog.getByRole('button', { name: 'Close' }))
  expect(actions().getByText('Approval requires an authoritative reference.')).toBeTruthy()
  expect(screen.queryByRole('checkbox')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Attach reference' })).toBeNull()
  expect(button('Approve').disabled).toBe(true)
  await expect(api.approve(manager.id, promotion, '')).rejects.toThrow()
})

it('requires fresh verification when navigating to a different draft', async () => {
  const api = createDevKnowledgeReviewApi()
  const response = deferred<Awaited<ReturnType<KnowledgeReviewApi['getForManager']>>>()
  const { router } = review(refund, {
    getForManager: (managerId, id) => id === missingParcel ? response.promise : api.getForManager(managerId, id),
  }, api)
  await screen.findByRole('button', { name: 'Approve' })
  verify()
  expect(button('Approve').disabled).toBe(false)
  await act(() => router.navigate(reviewPath(missingParcel)))
  expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
  expect(screen.getByRole('status').textContent).toBe('Loading knowledge entry…')
  await act(async () => response.resolve(await api.getForManager(manager.id, missingParcel)))
  expect(button('Approve').disabled).toBe(true)
  press('Verify reference')
  expect(screen.getByRole<HTMLInputElement>('checkbox').disabled).toBe(true)
  verify()
  press('Approve')
  await screen.findByRole('dialog', { name: 'Approved' })
  expect((await api.getForManager(manager.id, refund))?.entry.status).toBe('draft')
  expect((await api.getForManager(manager.id, missingParcel))?.entry.status).toBe('approved')
})

const publisher = { title: 'Publisher guideline', url: 'https://example.test/policy' }

it.each([
  { layer: 'layer1', authoredPolicyVersion: 'sha256:memoria', approvalReference: undefined },
  { layer: 'layer2', authoredPolicyVersion: undefined, approvalReference: publisher },
] as const)('directly approves the bound $layer version or reference', async (fields) => {
  const entry = await draftFixture(promotion, { ...fields, canAttachVerification: true })
  const approve = vi.fn().mockResolvedValue({ ...entry, status: 'approved' })
  review(entry.id, { approve, attachVerification: vi.fn(), getForManager: async () => ({ entry, canDecide: true }) })
  expect((await screen.findByRole<HTMLButtonElement>('button', { name: 'Approve' })).disabled).toBe(false)
  expect(screen.queryByRole('heading', { name: 'Attach a verification source' })).toBeNull()
  expect(screen.queryByRole('checkbox')).toBeNull()
  expect(approve).not.toHaveBeenCalled()
  press('Approve')
  await screen.findByRole('dialog', { name: 'Approved' })
  expect(approve).toHaveBeenCalledWith(
    manager.id, entry.id, fields.approvalReference?.url ?? null, entry.version, fields.authoredPolicyVersion,
  )
})

it('still requires verification after attaching an eligible pilot reference', async () => {
  const entry = await draftFixture(promotion, { canAttachVerification: true })
  const reference = { ...publisher, quote: 'Typically promotions only last 7 days.', version: entry.version }
  const attachVerification = vi.fn(async () => ({ ...entry, version: 'v2', verificationReference: publisher }))
  review(promotion, { attachVerification, getForManager: async () => ({ entry, canDecide: true }) })
  await screen.findByRole('heading', { name: 'Attach a verification source' })
  input('Source title', reference.title)
  input('Source URL', reference.url)
  input('Exact policy quotation', reference.quote)
  press('Attach reference')
  await screen.findByRole('button', { name: 'Verify reference' })
  expect(attachVerification).toHaveBeenCalledWith(manager.id, promotion, reference)
  expect(button('Approve').disabled).toBe(true)
  verify()
  expect(button('Approve').disabled).toBe(false)
})

it('retries approval, shows the popup, and grants and removes Agent access', async () => {
  const api = createDevKnowledgeReviewApi()
  const approve = vi.fn(api.approve).mockRejectedValueOnce(new Error('Offline'))
  const { router, knowledgeApi } = review(refund, { approve }, api)
  await screen.findByRole('button', { name: 'Approve' })
  expect(await knowledgeApi.getForAgent(agent.id, refund)).toBeNull()
  verify()
  press('Approve')
  await screen.findByText('The decision could not be saved. Please try again.')
  expect(screen.getByRole<HTMLInputElement>('checkbox').checked).toBe(true)
  expect(screen.queryByRole('dialog', { name: 'Approved' })).toBeNull()
  press('Approve')
  const popup = within(await screen.findByRole('dialog', { name: 'Approved' }))
  expect(popup.getByText('Agents can now see this in their Knowledge Base.')).toBeTruthy()
  fireEvent.click(popup.getByRole('button', { name: 'Done' }))
  expect(screen.queryByRole('region', { name: 'Decision' })).toBeNull()
  expect(button('Unapprove').disabled).toBe(false)
  expect(await knowledgeApi.getForAgent(agent.id, refund)).toMatchObject({ status: 'approved', approvedBy: 'Maya Chen' })
  fireEvent.click(screen.getByRole('link', { name: 'Knowledge drafts' }))
  await screen.findByRole('tab', { name: 'Approved (2)' })
  await act(() => router.navigate(reviewPath(refund) + '?tab=approved'))
  fireEvent.click(await screen.findByRole('button', { name: 'Unapprove' }))
  const dialog = () => within(screen.getByRole('dialog', { name: 'Unapprove this draft?' }))
  fireEvent.click(dialog().getByRole('button', { name: 'Cancel' }))
  expect(await knowledgeApi.getForAgent(agent.id, refund)).not.toBeNull()
  press('Unapprove')
  fireEvent.click(dialog().getByRole('button', { name: 'Unapprove' }))
  await screen.findByRole('button', { name: 'Approve' })
  expect(await knowledgeApi.getForAgent(agent.id, refund)).toBeNull()
  expect((await api.getForManager(manager.id, refund))?.entry.paragraphs).toEqual((await draftFixture(refund)).paragraphs)
})

it('requires a rejection reason, retains it on failure and updates the queue after retry', async () => {
  const api = createDevKnowledgeReviewApi()
  const reject = vi.fn(api.reject).mockRejectedValueOnce(new Error('Offline'))
  review(missingParcel, { reject }, api)
  fireEvent.click(await screen.findByRole('button', { name: 'Reject' }))
  const dialog = within(screen.getByRole('dialog'))
  const submit = dialog.getByRole<HTMLButtonElement>('button', { name: 'Reject' })
  expect(submit.disabled).toBe(true)
  input('Reason for rejection', 'Superseded by DL-03.')
  fireEvent.click(submit)
  await dialog.findByRole('alert')
  expect(field('Reason for rejection').value).toBe('Superseded by DL-03.')
  fireEvent.click(submit)
  await screen.findByText('Reason: Superseded by DL-03.')
  expect(reject).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('link', { name: 'Knowledge drafts' }))
  fireEvent.click(await screen.findByRole('tab', { name: 'Rejected (2)' }))
  expect(screen.getByRole('link', { name: 'Missing parcel claims' })).toBeTruthy()
})

it('shows the saved rejection outcome without actions', async () => {
  review('KD-095')
  await screen.findByText('Reason: Policy requires proof of purchase.')
  expect(actions().queryByRole('button')).toBeNull()
})
