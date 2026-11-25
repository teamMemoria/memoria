import type { ComponentProps } from 'react'
import { cleanup, render, fireEvent, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, vi } from 'vitest'
import { agent, callFixture, deferred } from '../test/callReview.test-data'
import { createDevApprovedKnowledgeApi } from '../test/devApprovedKnowledge'
import { createDevCallApi } from '../test/devCallApi'
import { createDevConversationsApi, createDevTeamReviewApi } from '../test/devTeamReviewApi'
import { createDevKnowledgeReviewApi } from '../test/devKnowledgeReview'
import type { Viewer } from '../types/viewer'
import App from './App'

export { agent, callFixture, createDevCallApi, deferred }

export const manager: Viewer = {
  id: 'manager-maya-chen',
  displayName: 'Maya Chen',
  role: 'manager',
}
export const callPath = '/agent/conversations/C1042'
export const findingPath = `${callPath}/findings/procedure-order`

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function createTestDependencies(callApi: ReturnType<typeof createDevCallApi>, knowledgeReviewApi: ReturnType<typeof createDevKnowledgeReviewApi>) {
  return {
    callApi,
    knowledgeReviewApi,
    conversationsApi: createDevConversationsApi(callApi),
    knowledgeApi: createDevApprovedKnowledgeApi(knowledgeReviewApi),
    teamReviewApi: createDevTeamReviewApi(callApi),
  }
}

export function openApp({
  path = '/',
  as = agent,
  fixtures = createDevCallApi(),
  drafts = createDevKnowledgeReviewApi(),
  ...overrides
}: Partial<ComponentProps<typeof App>> & {
  path?: string
  as?: Viewer
  fixtures?: ReturnType<typeof createDevCallApi>
  drafts?: ReturnType<typeof createDevKnowledgeReviewApi>
} = {}) {
  const router = createMemoryRouter([
    {
      path: '*',
      element: <App {...createTestDependencies(fixtures, drafts)} viewerApi={{ getViewer: async () => as }} {...overrides} />,
    },
  ], { initialEntries: [path] })
  const view = render(<RouterProvider router={router} />)
  return { router, ...view }
}

export async function chooseOption(label: string | RegExp, field: string | undefined = 'Review status') {
  const select = await screen.findByRole('combobox', { name: field || undefined })
  fireEvent.keyDown(select, { key: 'ArrowDown' })
  fireEvent.click(await screen.findByRole('option', { name: label }))
}

export function input(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

export function button(name: string | RegExp) {
  return screen.getByRole<HTMLButtonElement>('button', { name })
}

export function press(name: string | RegExp, scope: Pick<typeof screen, 'getByRole'> = screen) {
  fireEvent.click(scope.getByRole('button', { name }))
}

export function openCall(call: Awaited<ReturnType<typeof callFixture>> | null, path = callPath) {
  return openApp({ path, callApi: { ...createDevCallApi(), getCallForAgent: async () => call } })
}
