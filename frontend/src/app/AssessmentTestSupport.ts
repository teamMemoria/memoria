import { screen, within } from '@testing-library/react'
import { beforeEach, vi } from 'vitest'
import { callFixture, callPath, openCall, press } from './TestSetup'
import type { CallReview, CriterionId, ScoringCheck } from '../types/callReview'
import { categories } from '../features/assessment-shared/assessment'

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    disconnect() {}
  })
  Element.prototype.scrollTo = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
  window.scrollTo = vi.fn()
})

export async function inspect(name: string | RegExp, scope: Pick<typeof screen, 'getByRole'> = screen) {
  press(name, scope)
  return within(await screen.findByRole('dialog'))
}

export const path = `${callPath}/assessments/`

export async function openCategory(
  category = 'procedure',
  overrides: Partial<CallReview> = {},
) {
  const call = await callFixture(overrides)
  const app = openCall(call, path + category)
  await screen.findByRole('heading', {
    name: categories.find((item) => item.id === category)!.title,
    level: 1,
  })
  return { ...app, call }
}

export async function scoredCall(category: CriterionId) {
  const call = await callFixture({ findings: [], requestLinks: [] })
  const turn = call.transcript!.turns.find((item) => item.number === 8)!
  const unresolved = 'Purchase success is not established.'
  const checks: ScoringCheck[] = [
    {
      id: 'bounded-check', ruleId: 'test-rule', requirement: 'Confirm the required input',
      outcome: 'breach', earned: 0, maximum: 1, critical: true,
      explanation: 'A directly evidenced deduction.',
      advice: 'Check the required input before continuing.',
      citations: [
        {
          kind: 'conversation', conversation_id: 'authored-source', transcript_version: 'transcript-v1',
          turn_id: turn.number, event_kind: 'message', quote: turn.text,
        },
        {
          kind: 'reference', reference_id: 'authored-approved-rule', reference_version: 'rule-v2',
          section_id: 'prerequisite', quote: 'Verify the required input before continuing.',
        },
      ],
    },
    {
      id: 'unresolved-check', ruleId: 'test-rule-2', requirement: 'Observe the purchase outcome',
      outcome: 'unresolved', earned: null, maximum: 1, critical: false,
      explanation: unresolved, advice: '', citations: [],
    },
  ]
  call.criteria = [{
    ...call.criteria.find((item) => item.id === category)!,
    evidenceTurnNumbers: [],
    referenceId: null,
    scoring: {
      score: 75, coverage: 50, earned: 3, assessable: 4, possible: 8,
      processingError: null, limitations: [unresolved], checks,
      interpretationLimits: ['Account lookup does not establish identity.'],
    },
  }]
  return call
}

export { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
export { assessmentData } from '../features/assessment-shared/assessment'

export {
  callFixture,
  createDevCallApi,
  deferred,
  manager,
  openApp,
} from './TestSetup'
export { press } from './TestSetup'
export { vi } from 'vitest'
export type { CallReview } from '../types/callReview'
