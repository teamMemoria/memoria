import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react'
import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { createDevCallApi } from '../../lib/devCallApi'
import type { CallApi, CallReview } from '../../types/callReview'
import type { Viewer } from '../../types/viewer'
import { Procedure } from './Procedure'
import { Waveforms } from './Waveforms'

const viewer: Viewer = {
  id: 'agent-alex-morgan',
  displayName: 'Alex Morgan',
  role: 'agent',
}
const findingPath = '/agent/conversations/C1042/findings/procedure-order'
const originalShowModal = HTMLDialogElement.prototype.showModal
const originalClose = HTMLDialogElement.prototype.close

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true
  }
  HTMLDialogElement.prototype.close = function () {
    this.open = false
    this.dispatchEvent(new Event('close'))
  }
})
afterEach(cleanup)
afterAll(() => {
  HTMLDialogElement.prototype.showModal = originalShowModal
  HTMLDialogElement.prototype.close = originalClose
})

async function callFixture(overrides: Partial<CallReview> = {}) {
  const call = await createDevCallApi().getCallForAgent(viewer.id, 'C1042')
  if (!call) throw new Error('C1042 fixture is required')
  return { ...call, ...overrides }
}

function open({
  call,
  api = { getCallForAgent: async () => call ?? null },
  path = findingPath,
  currentViewer = viewer,
}: {
  call?: CallReview | null
  api?: CallApi | null
  path?: string
  currentViewer?: Viewer
} = {}) {
  const element = <Procedure viewer={currentViewer} api={api} />
  const router = createMemoryRouter(
    [
      {
        path: '/agent/conversations/:conversationId/findings/:findingId',
        element,
      },
      { path: '/agent/conversations/:conversationId/transcript', element },
      {
        path: '/agent/conversations/:conversationId',
        element: <h1>Call overview destination</h1>,
      },
    ],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
  return router
}

async function finding() {
  return screen.findByRole('heading', { name: 'Procedure finding' })
}

function selectedTurn() {
  return screen
    .getAllByRole('row')
    .filter((row) => row.getAttribute('data-selected') === 'true')
}

describe('procedure', () => {
  it('keeps waveforms decorative with independent clipping for each instance', () => {
    const { container } = render(
      <>
        <Waveforms />
        <Waveforms />
      </>,
    )

    const waveforms = container.querySelectorAll('svg')
    expect(waveforms).toHaveLength(6)
    for (const waveform of waveforms) {
      expect(waveform.getAttribute('aria-hidden')).toBe('true')
      expect(waveform.getAttribute('focusable')).toBe('false')
    }

    const clips = container.querySelectorAll('clipPath')
    expect(new Set([...clips].map((clip) => clip.id)).size).toBe(4)
    for (const group of container.querySelectorAll('g[clip-path]')) {
      const clipId = group.getAttribute('clip-path')!.slice(5, -1)
      expect([...clips].some((clip) => clip.id === clipId)).toBe(true)
    }
  })

  it('shows exact conversation passages separately from automatic feedback and the approved procedure', async () => {
    open({ call: await callFixture() })
    await finding()
    const evidence = screen.getByRole('region', {
      name: 'Conversation evidence',
    })
    const feedback = screen.getByRole('region', { name: 'Automatic feedback' })
    expect(within(feedback).getByRole('heading', { name: 'Required order', level: 3 })).toBeTruthy()
    expect(within(feedback).getByText('Procedure RP-01')).toBeTruthy()
    expect(within(feedback).getByText('Version 1')).toBeTruthy()
    expect(feedback.textContent).not.toContain('·')
    expect(within(evidence).getByText('I can offer you a refund.')).toBeTruthy()
    expect(
      within(evidence).getByText(
        'I’ve verified the purchase. The jacket is eligible.',
      ),
    ).toBeTruthy()
    expect(
      within(feedback).getByText(
        'Refund offered before purchase verification.',
      ),
    ).toBeTruthy()
    expect(within(feedback).getByText(/Suggested next step:/)).toBeTruthy()
    expect(
      screen.getByText('Illustrative waveform. Audio unavailable.'),
    ).toBeTruthy()
    expect(
      screen.getByRole<HTMLButtonElement>('button', { name: 'Next' }).disabled,
    ).toBe(true)
    expect(screen.queryByRole('button', { name: 'Add context' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Flag feedback' })).toBeNull()
  })

  it('highlights exactly the selected turn from timeline, procedure and transcript controls', async () => {
    const router = open({ call: await callFixture() })
    await finding()
    expect(selectedTurn()).toHaveLength(1)
    expect(selectedTurn()[0].id).toBe('transcript-turn-8')
    fireEvent.click(
      screen.getByRole('button', { name: 'Purchase verified at turn 13' }),
    )
    expect(selectedTurn()).toHaveLength(1)
    expect(selectedTurn()[0].id).toBe('transcript-turn-13')
    expect(router.state.location.search).toBe('?turn=13')
    fireEvent.click(screen.getByRole('button', { name: 'Turn 4' }))
    expect(selectedTurn()[0].id).toBe('transcript-turn-4')
    expect(screen.getByText('Could I have your full name?')).toBeTruthy()
    expect(screen.getByText('I can offer you a refund.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Select turn 8' }))
    expect(selectedTurn()[0].id).toBe('transcript-turn-8')
  })

  it('opens the correct approved reference and selected step, then closes without losing filters', async () => {
    const router = open({
      call: await callFixture(),
      path: `${findingPath}?q=refund&status=feedback-ready&turn=13`,
    })
    await finding()
    fireEvent.click(screen.getByRole('button', { name: 'View step 2 of RP-01' }))
    const dialog = screen.getByRole('dialog')
    expect(
      within(dialog).getByText(
        /Verify the order, customer match and refund eligibility before offering a refund/,
      ),
    ).toBeTruthy()
    expect(
      dialog.querySelector('.approved-reference-selected-step')?.textContent,
    ).toContain('Verify the order')
    expect(router.state.location.hash).toBe('#approved-reference')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(router.state.location.search).toBe(
      '?q=refund&status=feedback-ready&turn=13',
    )
    expect(router.state.location.hash).toBe('')
  })

  it('supports direct reference links from the overview and the complete transcript', async () => {
    const call = await callFixture()
    open({
      call,
      path: '/agent/conversations/C1042/transcript?turn=13#approved-reference',
    })
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByRole('heading', { name: call.references[0].title }),
    ).toBeTruthy()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
    expect(screen.getAllByRole('row')).toHaveLength(17)
    expect(selectedTurn()[0].id).toBe('transcript-turn-13')
  })

  it('connects complete transcript and return navigation while preserving the T2 filters', async () => {
    const router = open({
      call: await callFixture(),
      path: `${findingPath}?q=refund&status=feedback-ready&turn=8`,
    })
    await finding()
    fireEvent.click(screen.getByRole('link', { name: 'Complete transcript' }))
    await screen.findByRole('heading', {
      name: 'Complete conversation',
    })
    expect(screen.getAllByRole('row')).toHaveLength(17)
    expect(
      screen.getByText(
        /Your refund has been submitted to the original payment card/,
      ),
    ).toBeTruthy()
    await act(() => router.navigate(-1))
    await finding()
    expect(selectedTurn()[0].id).toBe('transcript-turn-8')
    await act(() => router.navigate(1))
    expect(screen.getAllByRole('row')).toHaveLength(17)
    fireEvent.click(screen.getByRole('link', { name: 'Call overview' }))
    expect(router.state.location.pathname).toBe('/agent/conversations/C1042')
    expect(router.state.location.search).toBe('?q=refund&status=feedback-ready')
  })

  it('opens the explicitly linked reference when a call has multiple applicable references', async () => {
    const call = await callFixture()
    call.references.push({
      ...call.references[0],
      id: 'RP-02',
      title: 'Second approved procedure',
      steps: [{ number: 1, text: 'The other applicable approved step.' }],
    })
    call.criteria[1].referenceId = 'RP-02'
    open({
      call,
      path: '/agent/conversations/C1042/transcript?reference=RP-02#approved-reference',
    })
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByRole('heading', {
        name: 'Second approved procedure',
      }),
    ).toBeTruthy()
    expect(
      within(dialog).getByText('The other applicable approved step.'),
    ).toBeTruthy()
    expect(
      within(dialog).queryByText(/Verify the order, customer match/),
    ).toBeNull()
  })

  it('does not substitute a reference when an explicit link is unknown or unrelated to the call', async () => {
    const call = await callFixture()
    call.references.push({
      ...call.references[0],
      id: 'RP-02',
      title: 'Unrelated procedure',
    })
    open({
      call,
      path: '/agent/conversations/C1042/transcript?reference=RP-02#approved-reference',
    })
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByRole('heading', {
        name: 'Approved reference unavailable',
      }),
    ).toBeTruthy()
    expect(within(dialog).queryByText('Unrelated procedure')).toBeNull()
  })

  it.each(['stale', 'disputed', 'draft'] as const)(
    'does not use %s references as proof of an agent error',
    async (status) => {
      const call = await callFixture()
      call.references[0].status = status
      open({ call })
      await finding()
      expect(
        screen.getByRole('heading', { name: 'Cannot assess' }),
      ).toBeTruthy()
      expect(
        screen.getByText('Missing evidence does not establish an agent error.'),
      ).toBeTruthy()
      expect(screen.queryByText(/Suggested next step:/)).toBeNull()
      fireEvent.click(screen.getByRole('button', { name: 'View step 2 of RP-01' }))
      const dialog = screen.getByRole('dialog')
      expect(
        within(dialog).getByRole('heading', {
          name: 'Approved reference unavailable',
        }),
      ).toBeTruthy()
      expect(
        within(dialog).queryByText(/Verify the order, customer match/),
      ).toBeNull()
    },
  )

  it('does not expose an approved reference that is unavailable to this Agent', async () => {
    const call = await callFixture()
    call.references[0].availableToAgentIds = ['another-agent']
    open({ call, path: `${findingPath}#approved-reference` })
    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByText(
        'An applicable approved reference is not available in your workspace.',
      ),
    ).toBeTruthy()
    expect(
      within(dialog).queryByText(/Verify the order, customer match/),
    ).toBeNull()
  })

  it('explains unavailable transcript evidence without claiming failure', async () => {
    open({ call: await callFixture({ transcript: null }) })
    await finding()
    expect(screen.getByRole('heading', { name: 'Cannot assess' })).toBeTruthy()
    expect(
      screen.getByText('Missing evidence does not establish an agent error.'),
    ).toBeTruthy()
    expect(screen.queryByText('Observed')).toBeNull()
    expect(screen.getAllByText('Evidence unavailable')).toHaveLength(3)
  })

  it('identifies a missing cited turn without claiming that an available reference is missing', async () => {
    const call = await callFixture()
    call.transcript!.turns = call.transcript!.turns.filter(
      (turn) => turn.number !== 13,
    )
    open({ call })
    await finding()
    expect(
      screen.getByText('Cited transcript turn 13 is unavailable.'),
    ).toBeTruthy()
    expect(
      screen.queryByText(
        'An applicable approved reference is unavailable, disputed or stale.',
      ),
    ).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'View step 2 of RP-01' }))
    expect(
      within(screen.getByRole('dialog')).getByText(
        /Verify the order, customer match/,
      ),
    ).toBeTruthy()
  })

  it('does not substitute another criterion’s reference when the finding has none', async () => {
    const call = await callFixture()
    call.findings[0].referenceId = null
    open({ call })
    await finding()
    expect(screen.getByRole('heading', { name: 'Cannot assess' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Approved reference' }))
    expect(
      within(screen.getByRole('dialog')).getByRole('heading', {
        name: 'Approved reference unavailable',
      }),
    ).toBeTruthy()
    expect(
      within(screen.getByRole('dialog')).queryByText(
        /Verify the order, customer match/,
      ),
    ).toBeNull()
  })

  it('shows loading and retries a failed request', async () => {
    const call = await callFixture()
    const api = {
      getCallForAgent: vi
        .fn()
        .mockRejectedValueOnce(new Error('offline'))
        .mockResolvedValueOnce(call),
    }
    open({ api })
    expect(screen.getByRole('status').textContent).toContain(
      'Loading conversation evidence',
    )
    expect(await screen.findByRole('alert')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await finding()
    expect(api.getCallForAgent).toHaveBeenCalledTimes(2)
    expect(api.getCallForAgent).toHaveBeenLastCalledWith(viewer.id, 'C1042')
  })

  it.each(['missing', 'other-agent'] as const)(
    'does not expose %s calls',
    async (kind) => {
      const call =
        kind === 'missing'
          ? null
          : await callFixture({ agentId: 'another-agent' })
      open({ call })
      expect(
        await screen.findByRole('heading', {
          name: 'Conversation unavailable',
        }),
      ).toBeTruthy()
      expect(screen.queryByText('I can offer you a refund.')).toBeNull()
    },
  )

  it('rejects a missing finding without inventing details', async () => {
    open({
      call: await callFixture(),
      path: '/agent/conversations/C1042/findings/unknown',
    })
    expect(
      await screen.findByRole('heading', { name: 'Finding unavailable' }),
    ).toBeTruthy()
    expect(screen.queryByText('I can offer you a refund.')).toBeNull()
  })

  it('explains processing feedback without exposing a premature finding', async () => {
    open({ call: await callFixture({ status: 'processing' }) })
    expect(
      await screen.findByRole('heading', { name: 'Feedback is processing' }),
    ).toBeTruthy()
    expect(screen.queryByText('I can offer you a refund.')).toBeNull()
  })

  it('labels a partial transcript and preserves its supplied limitation', async () => {
    const call = await callFixture()
    call.transcript = {
      complete: false,
      turns: call.transcript!.turns.slice(0, 8),
      unavailableReason: 'Only the first eight turns are available.',
    }
    open({ call, path: '/agent/conversations/C1042/transcript' })
    expect(
      await screen.findByRole('heading', {
        name: 'Available transcript',
      }),
    ).toBeTruthy()
    expect(
      screen.getByText('Only the first eight turns are available.'),
    ).toBeTruthy()
    expect(screen.getAllByRole('row')).toHaveLength(9)
  })

  it('does not fetch Agent evidence for a Manager', async () => {
    const api = { getCallForAgent: vi.fn() }
    open({ api, currentViewer: { ...viewer, role: 'manager' } })
    expect(
      screen.getByRole('heading', { name: 'Page unavailable for your role' }),
    ).toBeTruthy()
    expect(api.getCallForAgent).not.toHaveBeenCalled()
  })

  it('ignores a stale response after navigating to another conversation', async () => {
    const call = await callFixture()
    let resolveFirst!: (value: CallReview) => void
    const api: CallApi = {
      getCallForAgent: vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise<CallReview>((resolve) => {
              resolveFirst = resolve
            }),
        )
        .mockResolvedValueOnce(null),
    }
    const router = open({ api })
    await act(() =>
      router.navigate('/agent/conversations/OTHER/findings/procedure-order'),
    )
    await screen.findByRole('heading', { name: 'Conversation unavailable' })
    await act(() => resolveFirst(call))
    expect(screen.queryByText('I can offer you a refund.')).toBeNull()
    expect(
      screen.getByRole('heading', { name: 'Conversation unavailable' }),
    ).toBeTruthy()
  })
})
