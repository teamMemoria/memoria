import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import type { Viewer, ViewerApi } from '../types/viewer'
import App from './App'
import { createDependencies } from './dependencies'
import { createDevViewerApi } from '../lib/viewer'

afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
})

function renderApp(viewerApi: ViewerApi | null, path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App viewerApi={viewerApi} />
    </MemoryRouter>,
  )
}

describe('application layout', () => {
  it.each([
    ['agent', '/agent/conversations', 'My Conversations'],
    ['agent', '/agent/knowledge', 'Knowledge Base'],
    ['manager', '/manager/conversations', 'Team conversations'],
    ['manager', '/manager/knowledge', 'Knowledge drafts'],
  ] as const)(
    'opens the %s page at %s',
    async (role, path, heading) => {
      renderApp(createDevViewerApi(role), path)
      await screen.findByRole('heading', { name: heading })
    },
  )

  it('waits for the viewer before exposing role navigation', () => {
    renderApp({ getViewer: () => new Promise<Viewer | null>(() => {}) })
    expect(screen.getByRole('status').textContent).toContain(
      'Loading your workspace',
    )
    expect(screen.queryByRole('navigation')).toBeNull()
  })

  it('opens the Agent home and updates selected navigation with the URL', async () => {
    renderApp(createDevViewerApi('agent'))
    await screen.findByRole('heading', { name: 'My Conversations' })
    expect(
      screen
        .getByRole('link', { name: 'Conversations' })
        .getAttribute('aria-current'),
    ).toBe('page')
    expect(
      screen.queryByRole('link', { name: 'Team conversations' }),
    ).toBeNull()
    expect(
      screen.getByRole('link', { name: 'Knowledge Base' }).getAttribute('href'),
    ).toBe('/agent/knowledge')
    fireEvent.click(screen.getByRole('link', { name: 'Knowledge Base' }))
    await screen.findByRole('heading', { name: 'Knowledge Base' })
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

  it('opens a Manager deep link with Manager navigation', async () => {
    renderApp(createDevViewerApi('manager'), '/manager/knowledge')
    await screen.findByRole('heading', { name: 'Knowledge drafts' })
    expect(
      screen.getByRole('link', { name: 'Team conversations' }),
    ).toBeTruthy()
    expect(
      screen.getByRole('link', { name: 'Knowledge Base' }).getAttribute('href'),
    ).toBe('/manager/knowledge')
    expect(
      screen.getByRole('img', { name: 'Maya Chen, manager' }).textContent,
    ).toBe('MC')
  })

  it.each([
    ['agent', '/manager/conversations'],
    ['agent', '/manager/knowledge'],
    ['manager', '/agent/conversations'],
    ['manager', '/agent/knowledge'],
  ] as const)('does not show another role’s page to %s', async (role, path) => {
    renderApp(createDevViewerApi(role), path)
    await screen.findByRole('heading', {
      name: 'Page unavailable for your role',
    })
    expect(
      screen
        .getByRole('link', { name: 'Back to your conversations' })
        .getAttribute('href'),
    ).toBe(`/${role}/conversations`)
  })

  it.each([
    ['agent', '/', 'My Conversations'],
    ['agent', '/agent', 'My Conversations'],
    ['agent', '/agent/', 'My Conversations'],
    ['manager', '/', 'Team conversations'],
    ['manager', '/manager', 'Team conversations'],
    ['manager', '/manager/', 'Team conversations'],
  ] as const)('opens the %s home from %s', async (role, path, heading) => {
    renderApp(createDevViewerApi(role), path)
    await screen.findByRole('heading', { name: heading })
    expect(
      screen.getByRole('link', {
        name: role === 'agent' ? 'Conversations' : 'Team conversations',
      }).getAttribute('aria-current'),
    ).toBe('page')
  })

  it.each([
    ['agent', '/missing-page'],
    ['agent', '/agent/missing-page'],
    ['agent', '/manager/missing-page'],
    ['manager', '/missing-page'],
    ['manager', '/manager/missing-page'],
    ['manager', '/agent/missing-page'],
  ] as const)('returns %s home from unknown URL %s', async (role, path) => {
    renderApp(createDevViewerApi(role), path)
    await screen.findByRole('heading', { name: 'Page not found' })
    fireEvent.click(
      screen.getByRole('link', { name: 'Back to your conversations' }),
    )
    await screen.findByRole('heading', {
      name: role === 'agent' ? 'My Conversations' : 'Team conversations',
    })
  })

  it('retries a failed viewer request without exposing internal errors', async () => {
    const getViewer = vi
      .fn<ViewerApi['getViewer']>()
      .mockRejectedValueOnce(new Error('Internal connection details'))
      .mockResolvedValueOnce({ displayName: 'Alex Morgan', role: 'agent' })
    renderApp({ getViewer })
    await screen.findByRole('alert')
    expect(screen.queryByText('Internal connection details')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByRole('heading', { name: 'My Conversations' })
    expect(getViewer).toHaveBeenCalledTimes(2)
  })

  it.each([null, { getViewer: async () => null }])(
    'does not invent an unavailable identity',
    async (api) => {
      renderApp(api)
      await screen.findByRole('heading', {
        name: 'Your workspace is not available yet',
      })
      expect(screen.queryByRole('navigation')).toBeNull()
    },
  )

  it('keeps settings disabled until its feature exists', async () => {
    renderApp(createDevViewerApi('agent'))
    await screen.findByRole('navigation')
    expect(
      screen.getByRole<HTMLButtonElement>('button', {
        name: 'Settings (not available yet)',
      }).disabled,
    ).toBe(true)
  })
})

describe('dependency selection', () => {
  it('never provides a fixture viewer in production', () => {
    vi.stubEnv('DEV', false)
    vi.stubEnv('VITE_DEV_ROLE', 'manager')
    expect(createDependencies().viewerApi).toBeNull()
  })

  it('supports a Manager fixture only through development configuration', async () => {
    vi.stubEnv('DEV', true)
    vi.stubEnv('VITE_DEV_ROLE', 'manager')
    expect(await createDependencies().viewerApi?.getViewer()).toEqual({
      displayName: 'Maya Chen',
      role: 'manager',
    })
  })
})
