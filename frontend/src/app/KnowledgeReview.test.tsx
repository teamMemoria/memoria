import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { createDevApprovedKnowledgeApi } from '../lib/devApprovedKnowledge'
import { createDevKnowledgeReviewApi } from '../lib/devKnowledgeReview'
import type { KnowledgeReviewApi } from '../types/knowledge'
import { agent, deferred, manager, openApp } from './TestSetup'

const asManager = { getViewer: async () => manager }
const reviewPath = (id: string) => `/manager/knowledge/${id}`
const approve = () =>
  screen.getByRole<HTMLButtonElement>('button', { name: 'Approve' })
const checkbox = () => screen.getByRole<HTMLInputElement>('checkbox')
const openVerification = () =>
  fireEvent.click(screen.getByRole('button', { name: 'Verify reference' }))
const openReference = () => {
  const trigger = screen.getByRole('button', { name: 'Verify reference' })
  if (trigger.getAttribute('data-state') === 'closed') fireEvent.click(trigger)
  fireEvent.click(
    screen.getByRole('link', { name: /Open verification reference/ }),
  )
}

function openReview(
  id: string,
  knowledgeReviewApi: KnowledgeReviewApi = createDevKnowledgeReviewApi(),
) {
  return openApp({
    path: reviewPath(id),
    viewerApi: asManager,
    knowledgeReviewApi,
  })
}

describe('Manager knowledge verification and approval', () => {
  it('previews changes below Sources and saves them with the displayed draft version', async () => {
    const api = createDevKnowledgeReviewApi()
    const { entry } = (await api.getForManager(manager.id, 'KD-103'))!
    const draft = { ...entry, layer: 'layer2' as const, question: 'When do card refunds arrive?' }
    const updated = {
      ...draft, title: 'Card refund timing', version: 'new-version',
      paragraphs: ['Check the payment record.'], verificationReference: null,
    }
    const editDraft = vi.fn().mockResolvedValue(updated)
    openReview(draft.id, {
      ...api, editDraft,
      getForManager: async () => ({ entry: draft, canDecide: true, canEdit: true }),
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Edit draft' }))
    const form = screen.getByRole('form', { name: 'Edit draft' })
    fireEvent.change(within(form).getByRole('textbox', { name: 'Title' }), { target: { value: updated.title } })
    fireEvent.change(within(form).getByRole('textbox', { name: 'Guidance' }), { target: { value: updated.paragraphs[0] } })
    const viewer = screen.getByRole('region', { name: 'Draft document viewer' })
    expect(within(viewer).getByText(updated.title)).toBeTruthy()
    expect(approve().disabled).toBe(true)
    fireEvent.click(within(form).getByRole('button', { name: 'Save draft' }))
    expect(editDraft).toHaveBeenCalledWith(manager.id, draft.id, {
      title: updated.title, question: draft.question, guidance: updated.paragraphs[0], version: draft.version,
    })
    await screen.findByRole('heading', { name: updated.title, level: 1 })
    expect(screen.queryByRole('form', { name: 'Edit draft' })).toBeNull()
    expect(approve().disabled).toBe(true)
  })

  it('keeps a readable draft read-only when the backend has no decision endpoints', async () => {
    const api = createDevKnowledgeReviewApi()
    const approve = vi.fn(api.approve)
    const reject = vi.fn(api.reject)
    openReview('KD-103', { ...api, decisionsAvailable: false, approve, reject })
    await screen.findByText(/Knowledge drafts are read-only in this demo/)
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Edit draft' })).toBeNull()
    expect(screen.getByRole('link', { name: /Knowledge drafts/ })).toBeTruthy()
    expect(approve).not.toHaveBeenCalled()
    expect(reject).not.toHaveBeenCalled()
  })

  it('shows the draft, its supporting passages and the verification reference', async () => {
    openReview('KD-103')
    await screen.findByRole('heading', {
      name: 'Refund timing for card payments',
      level: 1,
    })
    const draft = screen.getByRole('region', { name: 'Knowledge entry' })
    expect(
      within(draft).getByText(
        'Card refunds usually appear within 5–10 business days.',
      ),
    ).toBeTruthy()
    const sources = screen.getByRole('region', { name: 'Sources' })
    fireEvent.click(
      within(sources).getByRole('button', { name: 'View source call C1058' }),
    )
    const passages = screen.getByRole('dialog', { name: 'Call C1058' })
    expect(within(passages).getByText('Turn 11')).toBeTruthy()
    expect(
      within(passages).getByText(
        'It can take 5 to 10 business days to reach your card.',
      ),
    ).toBeTruthy()
    fireEvent.click(within(passages).getByRole('button', { name: 'Close' }))
    const link = screen.getByRole('link', {
      name: /Open verification reference: Card refund policy RF-04 v2/,
    })
    expect(link.getAttribute('href')).toBe(
      'https://example.test/policies/RF-04',
    )
  })

  it('does not unlock approval with permission alone', async () => {
    openReview('KD-103')
    await screen.findByRole('region', { name: 'Decision' })
    expect(approve().disabled).toBe(true)
    openVerification()
    expect(checkbox().disabled).toBe(true)
    openReference()
    expect(approve().disabled).toBe(true)
    fireEvent.click(checkbox())
    expect(approve().disabled).toBe(false)
  })

  it('requires fresh verification when navigating directly to another draft', async () => {
    const api = createDevKnowledgeReviewApi()
    const response =
      deferred<Awaited<ReturnType<KnowledgeReviewApi['getForManager']>>>()
    const { router } = openReview('KD-103', {
      ...api,
      getForManager: (managerId, id) =>
        id === 'KD-102' ? response.promise : api.getForManager(managerId, id),
    })
    await screen.findByRole('region', { name: 'Decision' })
    openReference()
    fireEvent.click(checkbox())
    expect(approve().disabled).toBe(false)
    await act(() => router.navigate(reviewPath('KD-102')))
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    expect(screen.getByRole('status').textContent).toBe(
      'Loading knowledge entry…',
    )
    await act(async () =>
      response.resolve(await api.getForManager(manager.id, 'KD-102')),
    )
    openVerification()
    expect(checkbox().checked).toBe(false)
    expect(checkbox().disabled).toBe(true)
    expect(approve().disabled).toBe(true)
    openReference()
    expect(approve().disabled).toBe(true)
    fireEvent.click(checkbox())
    fireEvent.click(approve())
    await screen.findByRole('dialog', { name: 'Approved' })
    expect((await api.getForManager(manager.id, 'KD-102'))?.entry.status).toBe(
      'approved',
    )
    expect((await api.getForManager(manager.id, 'KD-103'))?.entry.status).toBe(
      'draft',
    )
  })

  it('does not treat repeated answers as verification when no reference exists', async () => {
    const reviewApi = createDevKnowledgeReviewApi()
    openReview('KD-104', { ...reviewApi, attachVerification: vi.fn() })
    const sources = await screen.findByRole('region', { name: 'Sources' })
    expect(within(sources).getAllByRole('button', { name: /^View source call / })).toHaveLength(3)
    const decision = screen.getByRole('region', { name: 'Decision' })
    expect(within(decision).getByText('Approval requires an authoritative reference.')).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Attach reference' })).toBeNull()
    expect(approve().disabled).toBe(true)
    await expect(reviewApi.approve(manager.id, 'KD-104', '')).rejects.toThrow()
  })

  it('publishes the exact Memoria-authored version when the Manager clicks Approve', async () => {
    const api = createDevKnowledgeReviewApi()
    const draft = (await api.getForManager(manager.id, 'KD-104'))!.entry
    const entry = { ...draft, layer: 'layer1' as const, authoredPolicyVersion: 'sha256:memoria' }
    const publish = vi.fn().mockResolvedValue({ ...entry, status: 'approved' })
    openReview('KD-104', {
      ...api,
      getForManager: async () => ({ entry, canDecide: true }),
      approve: publish,
    })
    await screen.findByRole('button', { name: 'Approve' })
    expect(screen.queryByText(/authoritative reference|current policy version/i)).toBeNull()
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(publish).not.toHaveBeenCalled()
    expect(approve().disabled).toBe(false)
    fireEvent.click(approve())
    await waitFor(() => expect(publish).toHaveBeenCalledWith(
      manager.id, entry.id, null, entry.version, entry.authoredPolicyVersion,
    ))
  })

  it('uses the supplied publisher reference for direct Layer 2 approval', async () => {
    const api = createDevKnowledgeReviewApi()
    const draft = (await api.getForManager(manager.id, 'KD-104'))!.entry
    const reference = { title: 'Publisher guideline', url: 'https://example.test/guideline' }
    const entry = {
      ...draft, layer: 'layer2' as const, canAttachVerification: true,
      approvalReference: reference, verificationReference: null,
    }
    const publish = vi.fn().mockResolvedValue({ ...entry, status: 'approved' })
    openReview(entry.id, {
      ...api, attachVerification: vi.fn(),
      getForManager: async () => ({ entry, canDecide: true }),
      approve: publish,
    })
    await screen.findByRole('link', { name: 'Open verification reference: Publisher guideline' })
    expect(screen.queryByRole('heading', { name: 'Attach a verification source' })).toBeNull()
    expect(screen.queryByText('Verification source needed.')).toBeNull()
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(approve().disabled).toBe(false)
    expect(publish).not.toHaveBeenCalled()
    fireEvent.click(approve())
    expect(publish).toHaveBeenCalledWith(manager.id, entry.id, reference.url, entry.version, undefined)
  })

  it('requires Manager verification after attaching a pilot source', async () => {
    const api = createDevKnowledgeReviewApi()
    const detail = await api.getForManager(manager.id, 'KD-104')
    if (!detail) throw new Error('Missing draft fixture')
    const reference = {
      title: 'Publisher guideline',
      url: 'https://example.test/policy',
      quote: 'Typically promotions only last 7 days.',
      version: detail.entry.version,
    }
    const attachVerification = vi.fn(async () => ({
      ...detail.entry,
      version: 'v2',
      verificationReference: { title: reference.title, url: reference.url },
    }))
    openReview('KD-104', {
      ...api,
      getForManager: async () => ({
        ...detail,
        entry: { ...detail.entry, canAttachVerification: true },
      }),
      attachVerification,
    })
    await screen.findByRole('heading', { name: 'Attach a verification source' })
    expect(approve().disabled).toBe(true)
    for (const [label, value] of [
      ['Source title', reference.title],
      ['Source URL', reference.url],
      ['Exact policy quotation', reference.quote],
    ]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
    fireEvent.click(screen.getByRole('button', { name: 'Attach reference' }))
    await screen.findByRole('button', { name: 'Verify reference' })
    expect(attachVerification).toHaveBeenCalledWith(manager.id, 'KD-104', reference)
    expect(approve().disabled).toBe(true)
    openReference()
    expect(approve().disabled).toBe(true)
    fireEvent.click(checkbox())
    expect(approve().disabled).toBe(false)
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
    await screen.findByText(
      'You do not have permission to approve or reject knowledge.',
    )
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull()
  })

  it('approves a verified entry, shows the outcome and makes it available to Agents', async () => {
    const reviewApi = createDevKnowledgeReviewApi()
    const knowledgeApi = createDevApprovedKnowledgeApi(reviewApi)
    const { router } = openApp({
      path: reviewPath('KD-103'),
      viewerApi: asManager,
      knowledgeReviewApi: reviewApi,
      knowledgeApi,
    })
    await screen.findByRole('region', { name: 'Decision' })
    openReference()
    fireEvent.click(checkbox())
    fireEvent.click(approve())
    const notice = await screen.findByRole('dialog', { name: 'Approved' })
    expect(within(notice).getByText('Agents can now see this in their Knowledge Base.')).toBeTruthy()
    fireEvent.click(within(notice).getByRole('button', { name: 'Done' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('region', { name: 'Decision' })).toBeNull()
    expect(screen.getByText('Approved', { selector: '.status-label' })).toBeTruthy()
    fireEvent.click(screen.getByRole('link', { name: 'Knowledge drafts' }))
    await screen.findByRole('tab', { name: 'Approved (2)' })
    expect(screen.getByRole('tab', { name: 'Pending review (2)' })).toBeTruthy()
    expect(await knowledgeApi.getForAgent(agent.id, 'KD-103')).toMatchObject({
      status: 'approved',
      approvedBy: 'Maya Chen',
    })
    await act(() => router.navigate('/manager/knowledge?tab=approved'))
    expect(
      screen.getByRole('link', { name: 'Refund timing for card payments' }),
    ).toBeTruthy()
    fireEvent.click(screen.getByRole('link', { name: 'Refund timing for card payments' }))
    await screen.findByRole('heading', { name: 'Refund timing for card payments', level: 1 })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('region', { name: 'Decision' })).toBeNull()
  })

  it('returns an approved draft to review and removes it from Agent knowledge', async () => {
    const reviewApi = createDevKnowledgeReviewApi()
    const knowledgeApi = createDevApprovedKnowledgeApi(reviewApi)
    const id = 'KD-103'
    const draft = await reviewApi.getForManager(manager.id, id)
    await reviewApi.approve(manager.id, id, draft?.entry.verificationReference?.url ?? null)
    expect(await knowledgeApi.getForAgent(agent.id, id)).not.toBeNull()

    openReview(id, reviewApi)
    const unapprove = { name: 'Unapprove' }
    fireEvent.click(await screen.findByRole('button', unapprove))
    const dialog = () => screen.getByRole('dialog', { name: 'Unapprove this draft?' })
    fireEvent.click(within(dialog()).getByRole('button', { name: 'Cancel' }))
    expect(await knowledgeApi.getForAgent(agent.id, id)).not.toBeNull()

    fireEvent.click(screen.getByRole('button', unapprove))
    fireEvent.click(within(dialog()).getByRole('button', unapprove))
    await screen.findByText('Pending review', { selector: '.status-label' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('button', unapprove)).toBeNull()
    expect(approve()).toBeTruthy()
    expect(await knowledgeApi.getForAgent(agent.id, id)).toBeNull()
    const updated = await reviewApi.getForManager(manager.id, id)
    expect(updated?.entry).toMatchObject({ status: 'draft', paragraphs: draft?.entry.paragraphs })
  })

  it('requires a reason to reject and moves the entry to the Rejected queue', async () => {
    openReview('KD-102')
    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }))
    const reject = within(
      screen.getByRole('dialog'),
    ).getByRole<HTMLButtonElement>('button', { name: 'Reject' })
    expect(reject.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Reason for rejection'), {
      target: { value: 'Superseded by DL-03.' },
    })
    fireEvent.click(reject)
    const decision = await screen.findByRole('region', { name: 'Decision' })
    await within(decision).findByText('Rejected')
    expect(
      within(decision).getByText('Reason: Superseded by DL-03.'),
    ).toBeTruthy()
    fireEvent.click(screen.getByRole('link', { name: 'Knowledge drafts' }))
    fireEvent.click(await screen.findByRole('tab', { name: 'Rejected (2)' }))
    expect(
      screen.getByRole('link', { name: 'Missing parcel claims' }),
    ).toBeTruthy()
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
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    fireEvent.change(screen.getByLabelText('Reason for rejection'), {
      target: { value: 'Draft reason' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    fireEvent.click(approve())
    expect((await screen.findByRole('alert')).textContent).toBe(
      'The decision could not be saved. Please try again.',
    )
    expect(checkbox().checked).toBe(true)
    expect(approve().disabled).toBe(false)
    expect(screen.queryByRole('dialog', { name: 'Approved' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))
    expect(
      screen.getByLabelText<HTMLTextAreaElement>('Reason for rejection').value,
    ).toBe('Draft reason')
  })

  it('shows the saved outcome for an entry that was already decided', async () => {
    openReview('KD-095')
    const decision = await screen.findByRole('region', { name: 'Decision' })
    expect(
      within(decision).getByText('Reason: Policy requires proof of purchase.'),
    ).toBeTruthy()
    expect(within(decision).queryByRole('button')).toBeNull()
  })

  it('returns focus after inspecting evidence without treating it as verification', async () => {
    openReview('KD-103')
    const source = await screen.findByRole('button', {
      name: 'View source call C1042',
    })
    source.focus()
    fireEvent.click(source)
    const dialog = await screen.findByRole('dialog', { name: 'Call C1042' })
    expect(within(dialog).getByText('Turn 15')).toBeTruthy()
    fireEvent.keyDown(dialog, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'View source call C1042' }),
      ).toBe(document.activeElement),
    )
    openVerification()
    expect(checkbox().disabled).toBe(true)
    expect(approve().disabled).toBe(true)
  })

  it('shows missing source evidence without inventing a passage', async () => {
    openReview('KD-104')
    fireEvent.click(
      await screen.findByRole('button', { name: 'View source call C1042' }),
    )
    const dialog = screen.getByRole('dialog', { name: 'Call C1042' })
    expect(
      within(dialog).getByText(
        'No conversation passages are available for this source.',
      ),
    ).toBeTruthy()
    expect(within(dialog).queryByRole('blockquote')).toBeNull()
  })

  it('keeps the rejection reason and allows retry when saving fails', async () => {
    const api = createDevKnowledgeReviewApi()
    const reject = vi
      .fn()
      .mockRejectedValueOnce(new Error('Offline'))
      .mockImplementationOnce(api.reject)
    openReview('KD-102', { ...api, reject })
    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }))
    const dialog = screen.getByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Reason for rejection'), {
      target: { value: 'Superseded by DL-03.' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject' }))
    await within(dialog).findByRole('alert')
    expect(
      within(dialog).getByLabelText<HTMLTextAreaElement>('Reason for rejection')
        .value,
    ).toBe('Superseded by DL-03.')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject' }))
    await within(
      await screen.findByRole('region', { name: 'Decision' }),
    ).findByText('Rejected')
    expect(reject).toHaveBeenCalledTimes(2)
  })
})
