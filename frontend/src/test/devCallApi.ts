import type { AuditCriterion, CallApi, CallFinding, CallReview, ReviewRequest, TranscriptTurn } from '../types/callReview'
import { refundProcedure } from './devApprovedKnowledge'

function transcript(rows: readonly [TranscriptTurn['speaker'], string, string][]) {
  return rows.map(([speaker, text, time], index) => ({ number: index + 1, speaker, text, time }))
}

function finding(fields: Omit<CallFinding, 'referenceId' | 'referenceStep' | 'procedureSteps'> &
  Partial<Pick<CallFinding, 'referenceId' | 'referenceStep' | 'procedureSteps'>>): CallFinding {
  return { referenceId: null, referenceStep: null, procedureSteps: [], ...fields }
}

const turns = transcript([
  ['Agent', 'Thanks for calling. How can I help?', '0:00'],
  ['Customer', 'I need help with a jacket I received.', '0:15'],
  ['Agent', 'Of course. Let me pull up your details.', '0:32'],
  ['Agent', 'Could I have your full name?', '1:18'],
  ['Customer', 'Jordan Lee.', '1:28'],
  ['Agent', 'Thank you, Jordan.', '1:35'],
  ['Customer', 'The jacket arrived damaged.', '1:48'],
  ['Agent', 'I can offer you a refund.', '2:02'],
  ['Customer', 'Can it go back to my card?', '2:15'],
  ['Agent', 'Yes, I can arrange that.', '2:27'],
  ['Agent', 'May I have your order number to verify the purchase?', '2:41'],
  ['Customer', 'The order number is J4821.', '3:00'],
  ['Agent', 'I’ve verified the purchase. The jacket is eligible.', '3:25'],
  ['Customer', 'Please refund the original card.', '3:40'],
  ['Agent', 'Your refund has been submitted to the original payment card. I’ll email the confirmation.', '4:05'],
  ['Customer', 'Yes, that answers all my questions. Thank you.', '4:32'],
])

const refundOrder = 'The refund was offered at turn 8. Purchase verification followed at turn 13. RP-01 v1, step 2, requires verification before a refund offer.'
const criteria: AuditCriterion[] = [
  {
    id: 'procedure', title: 'Procedure', result: 'needs-review',
    explanation: refundOrder, evidenceTurnNumbers: [8, 13], findingId: 'procedure-order', referenceId: 'RP-01',
  },
  {
    id: 'answer-support', title: 'Answer support', result: 'meets-criteria',
    explanation: 'The original-card refund agrees with RP-01 v1, step 3. The customer requests this method at turn 9; the agent confirms submission at turn 15.',
    evidenceTurnNumbers: [9, 15], findingId: null, referenceId: 'RP-01',
  },
  {
    id: 'completeness', title: 'Completeness', result: 'meets-criteria',
    explanation: 'The conversation addresses the damaged jacket, refund eligibility, payment method and confirmation. At turn 16, the customer says their questions were answered.',
    evidenceTurnNumbers: [7, 9, 13, 15, 16], findingId: null, referenceId: null,
  },
  {
    id: 'communication-style', title: 'Communication style', result: 'meets-criteria',
    explanation: 'The agent uses a polite request at turn 4, thanks Jordan at turn 6, and explains the refund outcome at turn 15. Text only. This assessment does not measure vocal tone.',
    evidenceTurnNumbers: [4, 6, 15], findingId: null, referenceId: null,
  },
]

const call: CallReview = {
  id: 'C1042',
  agentId: 'agent-alex-morgan',
  agentName: 'Alex Morgan',
  topic: 'Damaged jacket refund',
  date: '2026-10-08',
  duration: '4:32',
  summary: 'Refund submitted to the original payment card.',
  status: 'ready',
  criteria,
  findings: [
    {
      id: 'procedure-order',
      title: 'Refund offered before purchase verification.',
      criterionId: 'procedure',
      explanation: refundOrder,
      suggestion: 'Verify the purchase before offering a refund.',
      evidenceTurnNumbers: [8, 10, 11, 13],
      referenceId: 'RP-01',
      referenceStep: 2,
      procedureSteps: [
        { label: 'Identify customer', status: 'observed', turnNumbers: [4], note: null },
        { label: 'Verify purchase', status: 'observed', turnNumbers: [13], note: 'After offer' },
        { label: 'Offer refund', status: 'observed', turnNumbers: [8], note: null },
      ],
    },
  ],
  transcript: { complete: true, turns, unavailableReason: null },
  references: [refundProcedure],
  agentContext: null,
  reviewRequest: null,
  decision: null,
}

function recording(rows: Parameters<typeof transcript>[0], unavailableReason: string | null = null) {
  return { turns: transcript(rows), unavailableReason, complete: unavailableReason === null }
}

function teamCall(overrides: Partial<CallReview> & Pick<CallReview, 'id' | 'agentId' | 'agentName' | 'topic'>): CallReview {
  return { ...call, criteria: [], references: [], ...overrides }
}

function flag(findingId: string, reason: string, requestedAt: string, status: ReviewRequest['status'] = 'requested'): ReviewRequest {
  return { findingId, reason, requestedAt, status }
}

const teamCalls: CallReview[] = [
  teamCall({
    id: 'C1051',
    agentId: 'agent-priya-shah',
    agentName: 'Priya Shah',
    topic: 'Lamp exchange',
    date: '2026-10-12',
    duration: '3:10',
    summary: 'Exchange arranged for a damaged lamp.',
    findings: [finding({
        id: 'answer-support',
        title: 'Exchange offered without checking stock.',
        criterionId: 'answer-support',
        explanation: 'The exchange was offered at turn 3. No stock check is visible in the transcript.',
        suggestion: 'Check stock before offering an exchange.',
        evidenceTurnNumbers: [3],
    })],
    transcript: recording([
      ['Customer', 'My lamp arrived with a cracked shade.', '0:05'],
      ['Agent', 'I’m sorry about that. Let me look at your order.', '0:20'],
      ['Agent', 'I can swap the damaged lamp for a new one.', '1:02'],
      ['Customer', 'That would be great, thanks.', '1:15'],
    ]),
    agentContext: {
      text: 'I checked stock on the order screen while the customer was talking.',
      savedAt: '2026-10-13T09:20:00Z',
    },
    reviewRequest: flag('answer-support', 'Stock was checked in the order system before the call.', '2026-10-13T09:30:00Z'),
  }),
  teamCall({
    id: 'C1058',
    agentId: 'agent-sam-rivera',
    agentName: 'Sam Rivera',
    topic: 'Card refund timing',
    date: '2026-10-14',
    duration: '2:48',
    summary: 'Refund timing explained for a card payment.',
    findings: [finding({
        id: 'completeness',
        title: 'Refund timeline not confirmed with the customer.',
        criterionId: 'completeness',
        explanation: 'The agent explained the refund at turn 2. The customer’s confirmation is not visible.',
        suggestion: 'Confirm the customer understands the refund timeline.',
        evidenceTurnNumbers: [2],
        referenceId: 'RP-01',
        referenceStep: 4,
    })],
    transcript: recording([
      ['Customer', 'When will my refund reach my card?', '0:04'],
      ['Agent', 'It can take 5 to 10 business days to reach your card.', '0:31'],
    ], 'The recording ended before the call finished.'),
    references: [refundProcedure],
    reviewRequest: flag('completeness', 'The customer confirmed the timeline after the transcript cut off.', '2026-10-15T16:10:00Z'),
  }),
  teamCall({
    id: 'C1060',
    agentId: 'agent-priya-shah',
    agentName: 'Priya Shah',
    topic: 'Delivery delay',
    date: '2026-10-10',
    findings: [finding({
        id: 'procedure-order',
        title: 'Tracking checked after offering compensation.',
        criterionId: 'procedure',
        explanation: 'Compensation was offered at turn 2 and tracking was checked at turn 3.',
        suggestion: 'Check tracking before offering compensation.',
        evidenceTurnNumbers: [2, 3],
    })],
    transcript: recording([
      ['Customer', 'My parcel is three days late.', '0:06'],
      ['Agent', 'I can offer a delivery credit for the delay.', '0:40'],
      ['Agent', 'Tracking shows it arrives tomorrow.', '1:05'],
    ]),
    reviewRequest: flag('procedure-order', 'Tracking was checked on a second screen first.', '2026-10-11T11:00:00Z', 'complete'),
    decision: {
      outcome: 'dismissed',
      reason: 'The order system log shows tracking was checked first.',
      feedback: 'No change needed. Mentioning the tracking check aloud helps the record.',
      managerName: 'Maya Chen',
      decidedAt: '2026-10-11T15:00:00Z',
    },
  }),
]

export type ManagerDecision = NonNullable<CallReview['decision']>

export type DevCallApi = CallApi & {
  getCall(conversationId: string): Promise<CallReview | null>
  recordDecision(conversationId: string, decision: ManagerDecision): Promise<void>
}

export function createDevCallApi(): DevCallApi {
  // Each API keeps its own copy so saves survive navigation within a session.
  const saved = new Map(structuredClone([call, ...teamCalls]).map((entry) => [entry.id, entry]))

  function ownedCall(agentId: string, conversationId: string) {
    const target = saved.get(conversationId)
    if (!target || target.agentId !== agentId) {
      throw new Error('This conversation is not available.')
    }
    return target
  }

  return {
    async getCallForAgent(agentId, conversationId) {
      const target = saved.get(conversationId)
      return target && target.agentId === agentId ? structuredClone(target) : null
    },
    async saveContext(agentId, conversationId, text) {
      const target = ownedCall(agentId, conversationId)
      if (!text.trim()) throw new Error('Context cannot be empty.')
      target.agentContext = { text: text.trim(), savedAt: new Date().toISOString() }
      return structuredClone(target.agentContext)
    },
    async requestReview(agentId, conversationId, findingId, reason) {
      const target = ownedCall(agentId, conversationId)
      if (!target.findings.some((finding) => finding.id === findingId)) {
        throw new Error('This finding is not available.')
      }
      if (!reason.trim()) throw new Error('A reason is required.')
      if (target.reviewRequest) throw new Error('A review has already been requested.')
      target.reviewRequest = flag(findingId, reason.trim(), new Date().toISOString())
      return structuredClone(target.reviewRequest)
    },
    async getCall(conversationId) {
      const target = saved.get(conversationId)
      return target ? structuredClone(target) : null
    },
    async recordDecision(conversationId, decision) {
      const target = saved.get(conversationId)
      if (!target?.reviewRequest) throw new Error('No review was requested.')
      target.decision = structuredClone(decision)
      target.reviewRequest.status = 'complete'
    },
  }
}
