import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSidebarMotion } from './sidebarMotion.js'

beforeEach(() => vi.stubGlobal('requestAnimationFrame', undefined))
afterEach(() => {
  document.body.replaceChildren()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function createFixture(inShell = true) {
  const shell = document.createElement('div')
  if (inShell) shell.className = 'app-layout'
  const sidebar = document.createElement('aside')
  const logo = document.createElement('span')
  sidebar.append(logo)
  shell.append(sidebar)
  document.body.append(shell)
  const controller = createSidebarMotion(sidebar, logo, 'test-logo')
  return { shell, sidebar, logo, controller }
}

describe('connected shell surface', () => {
  it('shares the exact sidebar overlap without changing the grid width', () => {
    const { shell, sidebar, controller } = createFixture()
    expect(shell.style.getPropertyValue('--sidebar-overlap')).toBe('0px')
    controller.setExpanded(true)
    expect(sidebar.style.getPropertyValue('--sidebar-width')).toBe('288px')
    expect(shell.style.getPropertyValue('--sidebar-overlap')).toBe('200px')
    expect(shell.style.getPropertyValue('--sidebar-width')).toBe('')
    controller.setExpanded(false)
    expect(sidebar.style.getPropertyValue('--sidebar-width')).toBe('88px')
    expect(shell.style.getPropertyValue('--sidebar-overlap')).toBe('0px')
    controller.destroy()
  })

  it('cleans up the shared surface value and logo when destroyed', () => {
    const { shell, logo, controller } = createFixture()
    controller.setExpanded(true)
    controller.destroy()
    expect(shell.style.getPropertyValue('--sidebar-overlap')).toBe('')
    expect(logo.childElementCount).toBe(0)
  })

  it('keeps the surface synchronized on each frame and interrupted reversal', () => {
    let callback: FrameRequestCallback
    let now = 0
    vi.stubGlobal('requestAnimationFrame', (next: FrameRequestCallback) => {
      callback = next
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    vi.spyOn(performance, 'now').mockReturnValue(0)
    const { shell, sidebar, controller } = createFixture()
    function step() {
      now += 32
      callback(now)
      const width = parseFloat(sidebar.style.getPropertyValue('--sidebar-width'))
      const overlap = parseFloat(shell.style.getPropertyValue('--sidebar-overlap'))
      expect(overlap).toBeCloseTo(width - 88)
      return width
    }
    controller.setExpanded(true)
    const opening = step()
    expect(opening).toBeGreaterThan(88)
    expect(opening).toBeLessThan(288)
    controller.setExpanded(false)
    expect(step()).toBeLessThan(opening)
    controller.setExpanded(true)
    expect(step()).toBeGreaterThan(88)
    controller.destroy()
  })

  it('still works when a sidebar is rendered without an application shell', () => {
    const { shell, sidebar, controller } = createFixture(false)
    controller.setExpanded(true)
    expect(sidebar.style.getPropertyValue('--sidebar-width')).toBe('288px')
    expect(shell.style.getPropertyValue('--sidebar-overlap')).toBe('')
    controller.destroy()
  })

  it('opens and closes immediately when reduced motion is enabled', () => {
    const requestFrame = vi.fn()
    vi.stubGlobal('requestAnimationFrame', requestFrame)
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })))
    const { shell, sidebar, controller } = createFixture()
    controller.setExpanded(true)
    expect(sidebar.style.getPropertyValue('--sidebar-width')).toBe('288px')
    expect(shell.style.getPropertyValue('--sidebar-overlap')).toBe('200px')
    controller.setExpanded(false)
    expect(controller.isCollapsed()).toBe(true)
    expect(sidebar.style.getPropertyValue('--sidebar-width')).toBe('88px')
    expect(requestFrame).not.toHaveBeenCalled()
    controller.destroy()
  })

  it('settles an in-flight expansion when reduced motion is turned on', () => {
    let frame: FrameRequestCallback
    const preference = {
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
    const cancelFrame = vi.fn()
    vi.stubGlobal('matchMedia', () => preference)
    vi.stubGlobal('requestAnimationFrame', (next: FrameRequestCallback) => {
      frame = next
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', cancelFrame)
    vi.spyOn(performance, 'now').mockReturnValue(0)
    const { sidebar, controller } = createFixture()
    controller.setExpanded(true)
    frame!(32)
    expect(parseFloat(sidebar.style.getPropertyValue('--sidebar-width')))
      .toBeGreaterThan(88)
    preference.matches = true
    const listener = preference.addEventListener.mock.calls[0][1]
    listener()
    expect(sidebar.style.getPropertyValue('--sidebar-width')).toBe('288px')
    expect(cancelFrame).toHaveBeenCalledWith(1)
    controller.destroy()
  })

  it('cancels animation work and removes the preference listener on destroy', () => {
    const preference = {
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
    const cancelFrame = vi.fn()
    vi.stubGlobal('matchMedia', () => preference)
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 37))
    vi.stubGlobal('cancelAnimationFrame', cancelFrame)
    const { controller } = createFixture()
    controller.setExpanded(true)
    controller.destroy()
    expect(cancelFrame).toHaveBeenCalledWith(37)
    expect(preference.removeEventListener).toHaveBeenCalledWith(
      'change', preference.addEventListener.mock.calls[0][1],
    )
  })
})
