import { readFileSync } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Plugin } from 'vite'
import type { Conversation } from '../src/features/conversations/conversations.js'
import type { CallReview } from '../src/types/callReview.js'
import type { DemoProfile } from '../src/types/viewer.js'
import { simulationNarration } from './simulationNarration.js'

const cohort = '7388 749 5893 9055 10563 5930 835 1538 5870 2829 810 238 4097 10591 4684 5885 2169 635 4839 8240 10562 1846 6165 9211 5496'.split(' ')
const conversationPath = /^\/api\/(agent|manager)\/conversations(?:\/([^/]+)(?:\/turns\/(\d+)\/narration)?)?$/

function send(response: ServerResponse, status: number, body: unknown) {
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  })
  response.end(JSON.stringify(body))
}

export function simulationWorkspace(file: string | undefined, apiTarget: string, narrationDirectory: string): Plugin {
  if (!file) throw new Error('Set MEMORIA_SIMULATION_FILE to the archived 25-call scorecards.')
  const cards = JSON.parse(readFileSync(file, 'utf8')) as CallReview[]
  const readNarration = simulationNarration(narrationDirectory)
  const bySource = new Map(cards.map((card) => [card.sourceId, card]))
  if (cards.length !== cohort.length || !cohort.every((id) => bySource.has(id)) ||
      cards.some((card) => card.assessmentVersion?.scoringMethod !== 'calibrated-simulation-midpoint-v1' ||
        card.criteria.length !== 4 || !card.transcript || !Number.isFinite(card.overallScoring?.score))) {
    throw new Error('The demo requires the frozen 25 archived simulation scorecards.')
  }

  const perAgent = new Map<string, number>()
  for (const card of cards) {
    perAgent.set(card.agentName, (perAgent.get(card.agentName) ?? 0) + 1)
  }

  async function handle(request: IncomingMessage, response: ServerResponse, url: URL) {
    const path = url.pathname
    if (request.method !== 'GET') {
      send(response, 405, { detail: 'Simulation scorecards are read-only.' })
      return
    }
    const isProfiles = path === '/api/demo/profiles'
    const match = conversationPath.exec(path)
    if (!isProfiles && !match) {
      send(response, 404, { detail: 'Unavailable in the simulation.' })
      return
    }
    const user = request.headers['x-dev-user']
    if (!isProfiles && typeof user !== 'string') {
      send(response, 401, { detail: 'Choose a demo profile first.' })
      return
    }

    const role = match?.[1]
    // The backend authorizes the existing conversation inventory before any
    // archived scorecard is returned. Saved assessment details are never fetched.
    const source = await fetch(new URL(isProfiles ? path : `/api/${role}/conversations`, apiTarget), {
      headers: typeof user === 'string' ? { 'X-Dev-User': user } : {},
      signal: AbortSignal.timeout(8000),
    })
    if (!source.ok) {
      send(response, source.status, { detail: 'Demo workspace access is unavailable.' })
      return
    }
    if (isProfiles) {
      const profiles = await source.json() as DemoProfile[]
      send(response, 200, profiles.flatMap((profile) => {
        if (profile.role === 'manager') return [profile]
        const count = perAgent.get(profile.displayName)
        return count ? [{ ...profile, conversationCount: count }] : []
      }))
      return
    }

    const records = await source.json() as Conversation[]
    const rows = new Map(records.flatMap((record) => {
      const card = bySource.get(record.sourceId)
      if (!card || card.agentName !== record.agentName ||
          (role === 'agent' && record.agentId !== user)) return []
      return [[record.id, { record, card }] as const]
    }))
    const id = match?.[2]
    if (!id) {
      send(response, 200, Array.from(rows.values(), ({ record, card }) => ({
        id: record.id, sourceId: card.sourceId, agentId: record.agentId,
        agentName: record.agentName, topic: card.topic, date: null,
        automatedResult: 'cannot-assess', reviewStatus: null, flag: null,
        simulationScore: card.overallScoring?.score,
      })))
      return
    }

    const entry = rows.get(id)
    if (!entry) {
      send(response, 404, { detail: 'Conversation unavailable in the simulation.' })
      return
    }
    const { record, card } = entry
    if (match?.[3]) {
      const turn = card.transcript?.turns.find((entry) => entry.number === Number(match[3]))
      const result = await readNarration(turn, url.searchParams)
      if (result.audio) {
        response.writeHead(200, {
          'Content-Type': 'audio/mpeg',
          'Content-Length': result.audio.length,
          'Cache-Control': 'private, no-store',
          'X-Narration-Type': 'synthetic',
        })
        response.end(result.audio)
      } else {
        send(response, result.status, { detail: 'Generated narration unavailable for this turn.' })
      }
      return
    }
    const call: CallReview = {
      id: record.id, sourceId: card.sourceId, agentId: record.agentId,
      agentName: record.agentName, topic: card.topic, date: null, duration: null,
      summary: 'Archived ABCD transcript scored with simulation guidance and case facts.',
      assessmentSource: 'simulation',
      status: 'ready', overallScoring: card.overallScoring,
      assessmentVersion: card.assessmentVersion, criteria: card.criteria,
      transcript: card.transcript, findings: [], references: [],
      agentContext: null, reviewRequest: null, decision: null,
    }
    send(response, 200, role === 'manager' ? { call, canDecide: false } : call)
  }

  return {
    name: 'memoria-simulation-workspace',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const url = new URL(request.url ?? '/', 'http://localhost')
        const path = url.pathname
        if (path !== '/api/demo/profiles' && !/^\/api\/(agent|manager)\/conversations(?:\/|$)/.test(path)) {
          next()
          return
        }
        if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(request.socket.remoteAddress ?? '')) {
          send(response, 403, { detail: 'This demo is available on localhost.' })
          return
        }
        void handle(request, response, url).catch(() => {
          send(response, 503, { detail: 'Unable to load the simulation workspace.' })
        })
      })
    },
  }
}
