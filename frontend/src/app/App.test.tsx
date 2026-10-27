import { act, fireEvent, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Viewer } from '../types/viewer'
import { agent, deferred, manager, openApp } from './TestSetup'
import { createDependencies } from './dependencies'

describe('workspace access and navigation', () => {
  it('waits for identity, opens the Agent home and provides keyboard entry to content', async () => {
    const identity = deferred<Viewer | null>()
    openApp({ viewerApi: { getViewer: () => identity.promise } })
    expect(screen.getByRole('status').textContent).toContain('Loading your workspace')
    expect(screen.queryByRole('navigation')).toBeNull()
    await act(() => identity.resolve(agent))
    await screen.findByRole('heading', { name: 'My conversations' })
    expect(screen.getByRole('link', { name: 'Conversations' }).getAttribute('aria-current')).toBe('page')
    const main = screen.getByRole('main')
    expect(screen.getByRole('link', { name: 'Skip to content' }).getAttribute('href')).toBe('#' + main.id)
    act(() => main.focus())
    expect(document.activeElement).toBe(main)
    expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Settings (not available yet)' }).disabled).toBe(true)
  })

  it.each([null, { getViewer: async () => null }])('does not expose a workspace without an identity', async (viewerApi) => {
    openApp({ viewerApi })
    await screen.findByRole('heading', { name: 'Your workspace is not available yet' })
    expect(screen.queryByRole('navigation')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  })

  it('recovers from a sign-in failure and opens the returned Manager workspace', async () => {
    const getViewer = vi.fn().mockRejectedValueOnce(new Error('Internal connection details')).mockResolvedValueOnce(manager)
    openApp({ viewerApi: { getViewer } })
    await screen.findByRole('alert')
    expect(screen.queryByText('Internal connection details')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByRole('heading', { name: 'Team conversations' })
    expect(getViewer).toHaveBeenCalledTimes(2)
  })

  it('does not open development identities or fixture data in production', async () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_DEV_ROLE', 'manager')
    openApp(createDependencies())
    await screen.findByRole('heading', { name: 'Your workspace is not available yet' })
    expect(screen.queryByRole('navigation')).toBeNull()
    expect(screen.queryByText('Refund handling')).toBeNull()
  })

  it('keeps Manager navigation and selection consistent through direct links and history', async () => {
    const { router } = openApp({ path: '/manager/knowledge', viewerApi: { getViewer: async () => manager } })
    await screen.findByRole('heading', { name: 'Knowledge drafts' })
    const knowledge = screen.getByRole('link', { name: 'Knowledge Base' })
    expect(knowledge.getAttribute('aria-current')).toBe('page')
    fireEvent.click(screen.getByRole('link', { name: 'Team conversations' }))
    await screen.findByRole('heading', { name: 'Team conversations' })
    await act(() => router.navigate(-1))
    await screen.findByRole('heading', { name: 'Knowledge drafts' })
    expect(knowledge.getAttribute('aria-current')).toBe('page')
    await act(() => router.navigate(1))
    await screen.findByRole('heading', { name: 'Team conversations' })
    expect(screen.queryByRole('link', { name: 'Conversations' })).toBeNull()
  })

  it.each([
    { viewer: agent, path: '/manager/knowledge', home: 'My conversations' },
    { viewer: manager, path: '/agent/conversations/C1042/findings/procedure-order', home: 'Team conversations' },
  ])('blocks cross-role deep links for $viewer.role before requesting protected data', async ({ viewer, path, home }) => {
    const calls = vi.fn()
    const list = vi.fn()
    const detail = vi.fn()
    const conversations = vi.fn(async () => [])
    openApp({
      path,
      viewerApi: { getViewer: async () => viewer },
      callApi: { getCallForAgent: calls },
      conversationsApi: { listForAgent: conversations },
      knowledgeApi: { listForAgent: list, getForAgent: detail },
    })
    await screen.findByRole('heading', { name: 'Page unavailable for your role' })
    expect(calls).not.toHaveBeenCalled()
    expect(list).not.toHaveBeenCalled()
    expect(detail).not.toHaveBeenCalled()
    expect(conversations).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('link', { name: 'Back to your conversations' }))
    await screen.findByRole('heading', { name: home })
  })

  it.each([
    { viewer: agent, home: 'My conversations' },
    { viewer: manager, home: 'Team conversations' },
  ])('recovers from an unknown URL to the $viewer.role home', async ({ viewer, home }) => {
    openApp({ path: '/unknown', viewerApi: { getViewer: async () => viewer } })
    await screen.findByRole('heading', { name: 'Page not found' })
    fireEvent.click(screen.getByRole('link', { name: 'Back to your conversations' }))
    await screen.findByRole('heading', { name: home })
  })
})

describe('sidebar within the workspace', () => {
  it('supports delayed hover, cancelled opening and rapid return while navigating', async () => {
    let frame!: FrameRequestCallback
    openApp()
    await screen.findByRole('heading', { name: 'My conversations' })
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frame = callback
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    vi.spyOn(performance, 'now').mockReturnValue(0)
    const home = screen.getByRole('link', { name: 'Memoria home' })
    const sidebar = screen.getByRole('complementary', { name: 'Navigation' })
    fireEvent.pointerEnter(sidebar)
    act(() => vi.advanceTimersByTime(50))
    fireEvent.pointerLeave(sidebar)
    act(() => vi.advanceTimersByTime(100))
    expect(home.getAttribute('aria-expanded')).toBe('false')
    fireEvent.pointerEnter(sidebar)
    act(() => vi.advanceTimersByTime(99))
    expect(home.getAttribute('aria-expanded')).toBe('false')
    act(() => vi.advanceTimersByTime(1))
    expect(home.getAttribute('aria-expanded')).toBe('true')
    act(() => frame(32))
    fireEvent.pointerLeave(sidebar)
    act(() => vi.advanceTimersByTime(50))
    fireEvent.pointerEnter(sidebar)
    act(() => vi.advanceTimersByTime(100))
    expect(home.getAttribute('aria-expanded')).toBe('true')
    fireEvent.pointerLeave(sidebar)
    act(() => vi.advanceTimersByTime(100))
    expect(home.getAttribute('aria-expanded')).toBe('false')
    act(() => frame(48))
    fireEvent.pointerEnter(sidebar)
    expect(home.getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(screen.getByRole('link', { name: 'Knowledge Base' }))
    fireEvent.pointerLeave(sidebar)
    act(() => vi.advanceTimersByTime(100))
    expect(home.getAttribute('aria-expanded')).toBe('false')
    vi.useRealTimers()
    await screen.findByRole('heading', { name: 'Approved knowledge' })
  })

  it('opens for keyboard navigation, restores focus on Escape and dismisses outside the rail', async () => {
    openApp()
    await screen.findByRole('heading', { name: 'My conversations' })
    const home = screen.getByRole('link', { name: 'Memoria home' })
    const knowledge = screen.getByRole('link', { name: 'Knowledge Base' })
    act(() => knowledge.focus())
    expect(home.getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(knowledge)
    await screen.findByRole('list', { name: 'Approved entries' })
    expect(document.activeElement).toBe(knowledge)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(document.activeElement).toBe(home)
    expect(home.getAttribute('aria-expanded')).toBe('false')
    fireEvent.pointerDown(knowledge)
    expect(home.getAttribute('aria-expanded')).toBe('true')
    fireEvent.pointerDown(screen.getByRole('main'))
    expect(home.getAttribute('aria-expanded')).toBe('false')
    fireEvent.pointerDown(home)
    fireEvent.blur(window)
    expect(home.getAttribute('aria-expanded')).toBe('false')
  })

  it('keeps navigation usable with reduced motion and cancels pending opening on dismissal', async () => {
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: query.includes('prefers-reduced-motion') || query.includes('hover'),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })))
    const requestFrame = vi.fn()
    vi.stubGlobal('requestAnimationFrame', requestFrame)
    const { unmount } = openApp()
    await screen.findByRole('heading', { name: 'My conversations' })
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const home = screen.getByRole('link', { name: 'Memoria home' })
    const sidebar = screen.getByRole('complementary', { name: 'Navigation' })
    fireEvent.pointerEnter(sidebar)
    fireEvent.keyDown(document, { key: 'Escape' })
    act(() => vi.advanceTimersByTime(100))
    expect(home.getAttribute('aria-expanded')).toBe('false')
    fireEvent.pointerDown(home)
    expect(home.getAttribute('aria-expanded')).toBe('true')
    expect(requestFrame).not.toHaveBeenCalled()
    fireEvent.pointerLeave(sidebar)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
