import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useNavigate } from 'react-router'
import type { ViewerRole } from '../../types/viewer'
import { Sidebar } from './Sidebar'

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

function HistoryControls() {
  const navigate = useNavigate()
  return (
    <>
      <button onClick={() => navigate(-1)}>Back</button>
      <button onClick={() => navigate(1)}>Forward</button>
    </>
  )
}

function renderSidebar(
  role: ViewerRole = 'agent',
  path = `/${role}/conversations`,
) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar viewer={{ id: 'sidebar-user', displayName: 'Alex Morgan', role }} />
      <button>Page action</button>
      <HistoryControls />
    </MemoryRouter>,
  )
  return screen.getByRole('complementary', { name: 'Navigation' })
}

function advance(milliseconds: number) {
  act(() => vi.advanceTimersByTime(milliseconds))
}

describe('sidebar disclosure', () => {
  it('opens and closes after 100 ms hover delays', () => {
    const sidebar = renderSidebar()
    expect(sidebar.dataset.expanded).toBe('false')
    fireEvent.pointerEnter(sidebar)
    advance(99)
    expect(sidebar.dataset.expanded).toBe('false')
    advance(1)
    expect(sidebar.dataset.expanded).toBe('true')
    fireEvent.pointerLeave(sidebar)
    advance(99)
    expect(sidebar.dataset.expanded).toBe('true')
    advance(1)
    expect(sidebar.dataset.expanded).toBe('false')
  })

  it.each([72, 104])(
    'preserves hover delay and immediate reversal at a %s px collapsed width',
    (width) => {
      const root = document.documentElement
      const previousWidth = root.style.getPropertyValue('--sidebar-width')
      let frame: FrameRequestCallback
      vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
        frame = callback
        return 1
      })
      vi.stubGlobal('cancelAnimationFrame', vi.fn())
      vi.spyOn(performance, 'now').mockReturnValue(0)
      root.style.setProperty('--sidebar-width', `${width}px`)

      try {
        const sidebar = renderSidebar()
        fireEvent.pointerEnter(sidebar)
        advance(99)
        expect(sidebar.dataset.expanded).toBe('false')
        advance(1)
        expect(sidebar.dataset.expanded).toBe('true')
        act(() => frame(32))
        fireEvent.pointerLeave(sidebar)
        advance(100)
        expect(sidebar.dataset.expanded).toBe('false')
        act(() => frame(48))
        fireEvent.pointerEnter(sidebar)
        expect(sidebar.dataset.expanded).toBe('true')
      } finally {
        cleanup()
        if (previousWidth) root.style.setProperty('--sidebar-width', previousWidth)
        else root.style.removeProperty('--sidebar-width')
        vi.unstubAllGlobals()
        vi.restoreAllMocks()
      }
    },
  )

  it('ignores a brief pass over the rail and cancels closing on re-entry', () => {
    const sidebar = renderSidebar()
    fireEvent.pointerEnter(sidebar)
    advance(50)
    fireEvent.pointerLeave(sidebar)
    advance(300)
    expect(sidebar.dataset.expanded).toBe('false')
    fireEvent.pointerEnter(sidebar)
    advance(100)
    fireEvent.pointerLeave(sidebar)
    advance(50)
    fireEvent.pointerEnter(sidebar)
    advance(100)
    expect(sidebar.dataset.expanded).toBe('true')
  })

  it('opens for keyboard focus, stays open while focused and closes on blur', () => {
    const sidebar = renderSidebar()
    const link = screen.getByRole('link', { name: 'Conversations' })
    act(() => link.focus())
    expect(sidebar.dataset.expanded).toBe('true')
    fireEvent.pointerLeave(sidebar)
    advance(300)
    expect(sidebar.dataset.expanded).toBe('true')
    act(() => screen.getByRole('button', { name: 'Page action' }).focus())
    advance(250)
    expect(sidebar.dataset.expanded).toBe('false')
  })

  it('allows Escape to dismiss a hover-only opening and cancel pending opens', () => {
    const sidebar = renderSidebar()
    fireEvent.pointerEnter(sidebar)
    advance(100)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(sidebar.dataset.expanded).toBe('false')
    fireEvent.pointerLeave(sidebar)
    fireEvent.pointerEnter(sidebar)
    fireEvent.keyDown(document, { key: 'Escape' })
    advance(100)
    expect(sidebar.dataset.expanded).toBe('false')
  })

  it('opens immediately on a pointer press and dismisses on an outside press', () => {
    const sidebar = renderSidebar()
    fireEvent.pointerDown(
      screen.getByRole('link', { name: 'Knowledge Base' }),
    )
    expect(sidebar.dataset.expanded).toBe('true')
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Page action' }))
    expect(sidebar.dataset.expanded).toBe('false')
  })

  it('returns keyboard focus to the logo on Escape without reopening', () => {
    const sidebar = renderSidebar()
    act(() => screen.getByRole('link', { name: 'Conversations' }).focus())
    expect(sidebar.dataset.expanded).toBe('true')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(document.activeElement).toBe(
      screen.getByRole('link', { name: 'Memoria home' }),
    )
    advance(300)
    expect(sidebar.dataset.expanded).toBe('false')
  })

  it('dismisses on window blur and cancels a pending hover opening', () => {
    const sidebar = renderSidebar()
    fireEvent.pointerEnter(sidebar)
    fireEvent.blur(window)
    advance(300)
    expect(sidebar.dataset.expanded).toBe('false')
    fireEvent.pointerEnter(sidebar)
    advance(100)
    expect(sidebar.dataset.expanded).toBe('true')
    fireEvent.blur(window)
    expect(sidebar.dataset.expanded).toBe('false')
    advance(300)
    expect(sidebar.dataset.expanded).toBe('false')
  })

  it('cleans up scheduled work when unmounted', () => {
    const sidebar = renderSidebar()
    fireEvent.pointerEnter(sidebar)
    expect(vi.getTimerCount()).toBe(1)
    cleanup()
    expect(vi.getTimerCount()).toBe(0)
    fireEvent.keyDown(document, { key: 'Escape' })
  })
})

describe('route-driven sidebar selection', () => {
  it.each([
    ['agent', 'Conversations', 'Knowledge Base'],
    ['manager', 'Team conversations', 'Knowledge Base'],
  ] as const)(
    'updates %s selection and focus across navigation and history',
    (role, callsLabel, knowledgeLabel) => {
      renderSidebar(role)
      const nav = screen.getByRole('navigation', { name: 'Main navigation' })
      const selection = nav.querySelector('.sidebar-selection')
      const calls = screen.getByRole('link', { name: callsLabel })
      const knowledge = screen.getByRole('link', { name: knowledgeLabel })
      expect(calls.getAttribute('title')).toBe(callsLabel)
      expect(knowledge.getAttribute('title')).toBe(knowledgeLabel)
      expect(selection?.getAttribute('aria-hidden')).toBe('true')
      expect(calls.getAttribute('aria-current')).toBe('page')
      act(() => knowledge.focus())
      fireEvent.click(knowledge)
      expect(knowledge.getAttribute('aria-current')).toBe('page')
      expect(calls.getAttribute('aria-current')).toBeNull()
      expect(document.activeElement).toBe(knowledge)
      fireEvent.click(screen.getByRole('button', { name: 'Back' }))
      expect(calls.getAttribute('aria-current')).toBe('page')
      fireEvent.click(screen.getByRole('button', { name: 'Forward' }))
      expect(knowledge.getAttribute('aria-current')).toBe('page')
      expect(nav.querySelectorAll('.sidebar-selection')).toHaveLength(1)
    },
  )

  it('selects the Knowledge route on a direct load', () => {
    renderSidebar('agent', '/agent/knowledge')
    expect(
      screen
        .getByRole('link', { name: 'Knowledge Base' })
        .getAttribute('aria-current'),
    ).toBe('page')
    expect(
      screen
        .getByRole('link', { name: 'Conversations' })
        .getAttribute('aria-current'),
    ).toBeNull()
  })

  it('does not mark a navigation item active for an unrelated route', () => {
    renderSidebar('agent', '/missing')
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(nav.querySelector('[aria-current="page"]')).toBeNull()
  })
})
