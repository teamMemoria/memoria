import type { ComponentProps } from 'react'
import { cleanup, render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'
import { createDevConversationsApi } from '../features/conversations/devConversationsApi'
import { agent, callFixture, deferred } from '../lib/callReview.test-data'
import { createDevApprovedKnowledgeApi } from '../lib/devApprovedKnowledge'
import { createDevCallApi } from '../lib/devCallApi'
import type { Viewer } from '../types/viewer'
import App from './App'

export { agent, callFixture, deferred }

export const manager: Viewer = {
  id: 'manager-maya-chen',
  displayName: 'Maya Chen',
  role: 'manager',
}
export const callPath = '/agent/conversations/C1042'
export const findingPath = `${callPath}/findings/procedure-order`

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
afterAll(() => {
  HTMLDialogElement.prototype.showModal = originalShowModal
  HTMLDialogElement.prototype.close = originalClose
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

export function openApp({
  path = '/',
  ...overrides
}: Partial<ComponentProps<typeof App>> & { path?: string } = {}) {
  const router = createMemoryRouter([
    {
      path: '*',
      element: (
        <App
          viewerApi={{ getViewer: async () => agent }}
          conversationsApi={createDevConversationsApi()}
          callApi={createDevCallApi()}
          knowledgeApi={createDevApprovedKnowledgeApi()}
          {...overrides}
        />
      ),
    },
  ], { initialEntries: [path] })
  const view = render(<RouterProvider router={router} />)
  return { router, ...view }
}
