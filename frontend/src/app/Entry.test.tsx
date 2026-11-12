import { fireEvent, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DemoProfile, Viewer } from '../types/viewer'
import { agent, manager, openApp } from './TestSetup'

const profiles: DemoProfile[] = [
  { ...agent, conversationCount: 6 },
  { id: 'agent-sam-rivera', displayName: 'Sam Rivera', role: 'agent', conversationCount: 1 },
  { ...manager, conversationCount: null },
]

const profilesApi = { listProfiles: async () => profiles }
const viewerApi = {
  async getViewer(profileId?: string): Promise<Viewer | null> {
    const profile = profiles.find((item) => item.id === profileId)
    return profile ? { id: profile.id, displayName: profile.displayName, role: profile.role } : null
  },
}

function openEntry(overrides = {}) {
  return openApp({ profilesApi, viewerApi, ...overrides })
}

// A fresh in-memory localStorage for each test; TestSetup removes it afterwards.
beforeEach(() => {
  const items = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  })
})

describe('demo entry screen', () => {
  it('opens the chosen Agent profile on their own conversations', async () => {
    const { router } = openEntry()
    await screen.findByRole('heading', { name: 'Welcome to Memoria' })
    const continueButton = screen.getByRole<HTMLButtonElement>('button', { name: 'Continue' })
    expect(continueButton.disabled).toBe(true)
    expect(screen.getByText(/6 conversations/)).toBeTruthy()

    fireEvent.click(await screen.findByRole('radio', { name: /Alex Morgan/ }))
    fireEvent.click(continueButton)

    await screen.findByRole('heading', { name: 'My conversations' })
    expect(router.state.location.pathname).toBe('/agent/conversations')
    expect(screen.getByRole('img', { name: 'Alex Morgan, agent' })).toBeTruthy()
    expect(localStorage.getItem('memoria.demoProfile')).toBe('agent-alex-morgan')
  })

  it('opens the Manager dashboard with the demo Manager profile', async () => {
    openEntry()
    fireEvent.click(await screen.findByRole('radio', { name: 'Manager' }))
    expect(screen.queryByRole('radio', { name: /Alex Morgan/ })).toBeNull()
    fireEvent.click(screen.getByRole('radio', { name: /Maya Chen/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByRole('heading', { name: 'Team conversations' })
  })

  it('remembers the chosen profile across a reload', async () => {
    localStorage.setItem('memoria.demoProfile', 'manager-maya-chen')
    openEntry({ path: '/manager/knowledge' })
    await screen.findByRole('heading', { name: 'Knowledge drafts' })
    expect(screen.queryByRole('heading', { name: 'Welcome to Memoria' })).toBeNull()
  })

  it('asks again when the remembered profile no longer exists', async () => {
    localStorage.setItem('memoria.demoProfile', 'agent-removed')
    openEntry()
    await screen.findByText('That profile is no longer available. Choose another.')
    expect(screen.queryByRole('navigation')).toBeNull()
    expect(localStorage.getItem('memoria.demoProfile')).toBeNull()
  })

  it('never opens a different person than the one chosen', async () => {
    localStorage.setItem('memoria.demoProfile', 'agent-sam-rivera')
    openEntry({ viewerApi: { getViewer: async () => agent } })
    await screen.findByText('That profile is no longer available. Choose another.')
    expect(screen.queryByRole('navigation')).toBeNull()
  })

  it('shows an error with a retry when profiles cannot be loaded', async () => {
    const listProfiles = vi.fn()
      .mockRejectedValueOnce(new Error('Internal connection details'))
      .mockResolvedValueOnce(profiles)
    openEntry({ profilesApi: { listProfiles } })
    await screen.findByText("We couldn't load the demo profiles.")
    expect(screen.queryByText('Internal connection details')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByRole('radio', { name: /Alex Morgan/ })
    expect(listProfiles).toHaveBeenCalledTimes(2)
  })

  it('returns to the entry screen when switching profile', async () => {
    localStorage.setItem('memoria.demoProfile', 'agent-alex-morgan')
    openEntry()
    fireEvent.click(await screen.findByRole('button', { name: 'Switch profile' }))
    await screen.findByRole('heading', { name: 'Welcome to Memoria' })
    expect(localStorage.getItem('memoria.demoProfile')).toBeNull()
  })

  it('shows a still logo when reduced motion is preferred', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce') }))
    const { container } = openEntry()
    await screen.findByRole('heading', { name: 'Welcome to Memoria' })
    expect(container.querySelector('video')).toBeNull()
    expect(screen.getByRole('img', { name: 'Memoria' })).toBeTruthy()
  })

  it('plays the animated logo otherwise', async () => {
    const { container } = openEntry()
    await screen.findByRole('heading', { name: 'Welcome to Memoria' })
    expect(container.querySelector('video')?.getAttribute('src')).toBe('/brand/memoria-logo-animation.mp4')
  })
})
