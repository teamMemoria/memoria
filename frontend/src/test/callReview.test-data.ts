import type { CallReview } from '../types/callReview'
import type { Viewer } from '../types/viewer'
import { createDevCallApi } from './devCallApi'

export const agent: Viewer = {
  id: 'agent-alex-morgan',
  displayName: 'Alex Morgan',
  role: 'agent',
}

export async function callFixture(overrides: Partial<CallReview> = {}) {
  const call = await createDevCallApi().getCallForAgent(agent.id, 'C1042')
  if (!call) throw new Error('The C1042 development fixture is unavailable.')
  return { ...call, ...overrides }
}

export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}
