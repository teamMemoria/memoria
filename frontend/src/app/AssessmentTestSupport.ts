import { screen } from '@testing-library/react'
import { beforeEach, vi } from 'vitest'
import { callFixture, createDevCallApi, openApp } from './TestSetup'
import type { CallReview } from '../types/callReview'
import { categories } from '../features/assessment-shared/assessment'

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
  vi.stubGlobal('matchMedia', () => ({
    matches: true,
    addEventListener() {},
    removeEventListener() {},
  }))
  Element.prototype.scrollTo = vi.fn()
  Element.prototype.scrollIntoView = vi.fn()
  window.scrollTo = vi.fn()
})
export const path = '/agent/conversations/C1042/assessments/'

export async function openCategory(
  category = 'procedure',
  overrides: Partial<CallReview> = {},
) {
  const call = await callFixture(overrides)
  const api = {
    ...createDevCallApi(),
    getCallForAgent: vi.fn(async () => call),
  }
  const app = openApp({ path: path + category, callApi: api })
  await screen.findByRole('heading', {
    name: categories.find((item) => item.id === category)!.title,
    level: 1,
  })
  return { ...app, call, api }
}

export async function scoredCall(
  category: CallReview['criteria'][number]['id'],
) {
  const call = await callFixture({ findings: [], requestLinks: [] })
  const turn = call.transcript!.turns.find((item) => item.number === 8)!
  call.criteria = [
    {
      ...call.criteria.find((item) => item.id === category)!,
      evidenceTurnNumbers: [],
      referenceId: null,
      scoring: {
        score: 75,
        coverage: 50,
        earned: 3,
        assessable: 4,
        possible: 8,
        processingError: null,
        limitations: ['Purchase success is not established.'],
        interpretationLimits: ['Account lookup does not establish identity.'],
        checks: [
          {
            id: 'bounded-check',
            ruleId: 'test-rule',
            requirement: 'Confirm the required input',
            outcome: 'breach',
            earned: 0,
            maximum: 1,
            critical: true,
            explanation: 'A directly evidenced deduction.',
            advice: 'Check the required input before continuing.',
            citations: [
              {
                kind: 'conversation',
                conversation_id: 'authored-source',
                transcript_version: 'transcript-v1',
                turn_id: turn.number,
                event_kind: 'message',
                quote: turn.text,
              },
              {
                kind: 'reference',
                reference_id: 'authored-approved-rule',
                reference_version: 'rule-v2',
                section_id: 'prerequisite',
                quote: 'Verify the required input before continuing.',
              },
            ],
          },
          {
            id: 'unresolved-check',
            ruleId: 'test-rule-2',
            requirement: 'Observe the purchase outcome',
            outcome: 'unresolved',
            earned: null,
            maximum: 1,
            critical: false,
            explanation: 'Purchase success is not established.',
            advice: '',
            citations: [],
          },
        ],
      },
    },
  ]
  return call
}

export { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
export {
  callFixture,
  createDevCallApi,
  deferred,
  manager,
  openApp,
} from './TestSetup'
export {
  assessmentData,
  categories,
} from '../features/assessment-shared/assessment'
export { vi } from 'vitest'
export type { CallReview } from '../types/callReview'
