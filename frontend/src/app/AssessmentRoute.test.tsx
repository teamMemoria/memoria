import { act, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { callFixture, createDevCallApi, deferred, manager, openApp } from './TestSetup'
import type { CallReview } from '../types/callReview'

const path = '/agent/conversations/C1042/assessments/'

describe('existing assessment contract', () => {
  it.each(['procedure', 'completeness', 'answer-support', 'communication-style'])(
    'reads %s without scoring extensions or invented percentages', async (category) => {
      const call = await callFixture({ date: null, duration: null })
      const criterion = call.criteria.find((item) => item.id === category)!
      openApp({ path: path + category, callApi: { ...createDevCallApi(), getCallForAgent: async () => call } })
      await screen.findByRole('heading', { name: criterion.title, level: 1 })
      expect(within(screen.getByRole('region', { name: 'Recorded assessment' })).getByText(criterion.explanation)).toBeTruthy()
      expect(screen.queryByText(/\d+%/)).toBeNull()
      expect(screen.getByRole('region', { name: 'Transcript' })).toBeTruthy()
    },
  )

  it('does not expose an assessment assigned to a different agent', async () => {
    const call = await callFixture({ agentId: 'other-agent' })
    openApp({ path: path + 'procedure', callApi: { ...createDevCallApi(), getCallForAgent: async () => call } })
    await screen.findByRole('heading', { name: 'Conversation unavailable' })
    expect(screen.queryByRole('region', { name: 'Transcript' })).toBeNull()
  })

  it('ignores a late assessment response after navigation', async () => {
    const old = deferred<CallReview | null>()
    const api = { ...createDevCallApi(), getCallForAgent: (_: string, id: string) => id === 'C1042' ? old.promise : Promise.resolve(null) }
    const { router } = openApp({ path: path + 'procedure', callApi: api })
    await screen.findByText('Loading assessment…')
    await act(() => router.navigate('/agent/conversations/other/assessments/procedure'))
    await screen.findByRole('heading', { name: 'Conversation unavailable' })
    await act(async () => old.resolve(await callFixture()))
    expect(screen.getByRole('heading', { name: 'Conversation unavailable' })).toBeTruthy()
  })

  it('lets a Manager read a permitted conversation using the Manager API', async () => {
    const call = await callFixture()
    openApp({ path: '/manager/conversations/C1042/assessments/procedure',
      viewerApi: { getViewer: async () => manager },
      teamReviewApi: { listForManager: async () => [], getCallForManager: async () => ({ call, canDecide: false }), saveDecision: async () => { throw new Error('not used') } },
    })
    await screen.findByRole('heading', { name: 'Procedure', level: 1 })
    expect(screen.getByRole('region', { name: 'Transcript' })).toBeTruthy()
  })

  it('reports unavailable cited turns without manufacturing passages', async () => {
    const call = await callFixture()
    call.criteria[0].evidenceTurnNumbers = [9999]
    call.references = call.references.map((entry) => ({ ...entry, status: 'draft' }))
    openApp({ path: path + call.criteria[0].id, callApi: { ...createDevCallApi(), getCallForAgent: async () => call } })
    await screen.findByText('Cited turn 9999 is unavailable in the supplied transcript.')
    expect(screen.queryByText('Approved by')).toBeNull()
  })
})
