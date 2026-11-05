import type { CallApi, CallReview, TranscriptTurn } from '../types/callReview'
import { refundProcedure } from './devApprovedKnowledge'

const turns: TranscriptTurn[] = [
  {
    number: 1,
    speaker: 'Agent',
    text: 'Thanks for calling. How can I help?',
    time: '0:00',
  },
  {
    number: 2,
    speaker: 'Customer',
    text: 'I need help with a jacket I received.',
    time: '0:15',
  },
  {
    number: 3,
    speaker: 'Agent',
    text: 'Of course. Let me pull up your details.',
    time: '0:32',
  },
  {
    number: 4,
    speaker: 'Agent',
    text: 'Could I have your full name?',
    time: '1:18',
  },
  { number: 5, speaker: 'Customer', text: 'Jordan Lee.', time: '1:28' },
  { number: 6, speaker: 'Agent', text: 'Thank you, Jordan.', time: '1:35' },
  {
    number: 7,
    speaker: 'Customer',
    text: 'The jacket arrived damaged.',
    time: '1:48',
  },
  {
    number: 8,
    speaker: 'Agent',
    text: 'I can offer you a refund.',
    time: '2:02',
  },
  {
    number: 9,
    speaker: 'Customer',
    text: 'Can it go back to my card?',
    time: '2:15',
  },
  {
    number: 10,
    speaker: 'Agent',
    text: 'Yes, I can arrange that.',
    time: '2:27',
  },
  {
    number: 11,
    speaker: 'Agent',
    text: 'May I have your order number to verify the purchase?',
    time: '2:41',
  },
  {
    number: 12,
    speaker: 'Customer',
    text: 'The order number is J4821.',
    time: '3:00',
  },
  {
    number: 13,
    speaker: 'Agent',
    text: 'I’ve verified the purchase. The jacket is eligible.',
    time: '3:25',
  },
  {
    number: 14,
    speaker: 'Customer',
    text: 'Please refund the original card.',
    time: '3:40',
  },
  {
    number: 15,
    speaker: 'Agent',
    text: 'Your refund has been submitted to the original payment card. I’ll email the confirmation.',
    time: '4:05',
  },
  {
    number: 16,
    speaker: 'Customer',
    text: 'Yes, that answers all my questions. Thank you.',
    time: '4:32',
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
  criteria: [
    {
      id: 'procedure',
      title: 'Procedure',
      result: 'needs-review',
      explanation:
        'The refund was offered at turn 8. Purchase verification followed at turn 13. RP-01 v1, step 2, requires verification before a refund offer.',
      evidenceTurnNumbers: [8, 13],
      findingId: 'procedure-order',
      referenceId: 'RP-01',
    },
    {
      id: 'answer-support',
      title: 'Answer support',
      result: 'meets-criteria',
      explanation:
        'The original-card refund agrees with RP-01 v1, step 3. The customer requests this method at turn 9; the agent confirms submission at turn 15.',
      evidenceTurnNumbers: [9, 15],
      findingId: null,
      referenceId: 'RP-01',
    },
    {
      id: 'completeness',
      title: 'Completeness',
      result: 'meets-criteria',
      explanation:
        'The conversation addresses the damaged jacket, refund eligibility, payment method and confirmation. At turn 16, the customer says their questions were answered.',
      evidenceTurnNumbers: [7, 9, 13, 15, 16],
      findingId: null,
      referenceId: null,
    },
    {
      id: 'communication-style',
      title: 'Communication style',
      result: 'meets-criteria',
      explanation:
        'The agent uses a polite request at turn 4, thanks Jordan at turn 6, and explains the refund outcome at turn 15. Text only. This assessment does not measure vocal tone.',
      evidenceTurnNumbers: [4, 6, 15],
      findingId: null,
      referenceId: null,
    },
  ],
  findings: [
    {
      id: 'procedure-order',
      title: 'Refund offered before purchase verification.',
      criterionId: 'procedure',
      explanation:
        'The refund was offered at turn 8. Purchase verification followed at turn 13. RP-01 v1, step 2, requires verification before a refund offer.',
      suggestion: 'Verify the purchase before offering a refund.',
      evidenceTurnNumbers: [8, 10, 11, 13],
      referenceId: 'RP-01',
      referenceStep: 2,
      procedureSteps: [
        {
          label: 'Identify customer',
          status: 'observed',
          turnNumbers: [4],
          note: null,
        },
        {
          label: 'Verify purchase',
          status: 'observed',
          turnNumbers: [13],
          note: 'After offer',
        },
        {
          label: 'Offer refund',
          status: 'observed',
          turnNumbers: [8],
          note: null,
        },
      ],
    },
  ],
  transcript: { complete: true, turns, unavailableReason: null },
  references: [refundProcedure],
  agentContext: null,
  reviewRequest: null,
  decision: null,
}

// Team calls Managers can review in development.
function teamCall(overrides: Partial<CallReview> & Pick<CallReview, 'id' | 'agentId' | 'agentName' | 'topic'>): CallReview {
  return {
    ...structuredClone(call),
    criteria: [],
    references: [],
    agentContext: null,
    reviewRequest: null,
    decision: null,
    ...overrides,
  }
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
    findings: [
      {
        id: 'answer-support',
        title: 'Exchange offered without checking stock.',
        criterionId: 'answer-support',
        explanation: 'The exchange was offered at turn 3. No stock check is visible in the transcript.',
        suggestion: 'Check stock before offering an exchange.',
        evidenceTurnNumbers: [3],
        referenceId: null,
        referenceStep: null,
        procedureSteps: [],
      },
    ],
    transcript: {
      complete: true,
      unavailableReason: null,
      turns: [
        { number: 1, speaker: 'Customer', text: 'My lamp arrived with a cracked shade.', time: '0:05' },
        { number: 2, speaker: 'Agent', text: 'I’m sorry about that. Let me look at your order.', time: '0:20' },
        { number: 3, speaker: 'Agent', text: 'I can swap the damaged lamp for a new one.', time: '1:02' },
        { number: 4, speaker: 'Customer', text: 'That would be great, thanks.', time: '1:15' },
      ],
    },
    agentContext: {
      text: 'I checked stock on the order screen while the customer was talking.',
      savedAt: '2026-10-13T09:20:00Z',
    },
    reviewRequest: {
      findingId: 'answer-support',
      reason: 'Stock was checked in the order system before the call.',
      requestedAt: '2026-10-13T09:30:00Z',
      status: 'requested',
    },
  }),
  teamCall({
    id: 'C1058',
    agentId: 'agent-sam-rivera',
    agentName: 'Sam Rivera',
    topic: 'Card refund timing',
    date: '2026-10-14',
    duration: '2:48',
    summary: 'Refund timing explained for a card payment.',
    findings: [
      {
        id: 'completeness',
        title: 'Refund timeline not confirmed with the customer.',
        criterionId: 'completeness',
        explanation: 'The agent explained the refund at turn 2. The customer’s confirmation is not visible.',
        suggestion: 'Confirm the customer understands the refund timeline.',
        evidenceTurnNumbers: [2],
        referenceId: 'RP-01',
        referenceStep: 4,
        procedureSteps: [],
      },
    ],
    transcript: {
      complete: false,
      unavailableReason: 'The recording ended before the call finished.',
      turns: [
        { number: 1, speaker: 'Customer', text: 'When will my refund reach my card?', time: '0:04' },
        { number: 2, speaker: 'Agent', text: 'It can take 5 to 10 business days to reach your card.', time: '0:31' },
      ],
    },
    references: [refundProcedure],
    reviewRequest: {
      findingId: 'completeness',
      reason: 'The customer confirmed the timeline after the transcript cut off.',
      requestedAt: '2026-10-15T16:10:00Z',
      status: 'requested',
    },
  }),
  teamCall({
    id: 'C1060',
    agentId: 'agent-priya-shah',
    agentName: 'Priya Shah',
    topic: 'Delivery delay',
    date: '2026-10-10',
    findings: [
      {
        id: 'procedure-order',
        title: 'Tracking checked after offering compensation.',
        criterionId: 'procedure',
        explanation: 'Compensation was offered at turn 2 and tracking was checked at turn 3.',
        suggestion: 'Check tracking before offering compensation.',
        evidenceTurnNumbers: [2, 3],
        referenceId: null,
        referenceStep: null,
        procedureSteps: [],
      },
    ],
    transcript: {
      complete: true,
      unavailableReason: null,
      turns: [
        { number: 1, speaker: 'Customer', text: 'My parcel is three days late.', time: '0:06' },
        { number: 2, speaker: 'Agent', text: 'I can offer a delivery credit for the delay.', time: '0:40' },
        { number: 3, speaker: 'Agent', text: 'Tracking shows it arrives tomorrow.', time: '1:05' },
      ],
    },
    reviewRequest: {
      findingId: 'procedure-order',
      reason: 'Tracking was checked on a second screen first.',
      requestedAt: '2026-10-11T11:00:00Z',
      status: 'complete',
    },
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
  // Development-only access for the Manager team review API.
  getCall(conversationId: string): Promise<CallReview | null>
  recordDecision(conversationId: string, decision: ManagerDecision): Promise<void>
}

export function createDevCallApi(): DevCallApi {
  // Each API keeps its own copy so saves survive navigation within a session.
  const saved = structuredClone([call, ...teamCalls])

  function ownedCall(agentId: string, conversationId: string) {
    const target = saved.find((item) => item.id === conversationId)
    if (!target || target.agentId !== agentId) {
      throw new Error('This conversation is not available.')
    }
    return target
  }

  return {
    async getCallForAgent(agentId, conversationId) {
      const target = saved.find((item) => item.id === conversationId)
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
      if (target.reviewRequest) {
        throw new Error('A review has already been requested.')
      }
      target.reviewRequest = {
        findingId,
        reason: reason.trim(),
        requestedAt: new Date().toISOString(),
        status: 'requested',
      }
      return structuredClone(target.reviewRequest)
    },
    async getCall(conversationId) {
      const target = saved.find((item) => item.id === conversationId)
      return target ? structuredClone(target) : null
    },
    async recordDecision(conversationId, decision) {
      const target = saved.find((item) => item.id === conversationId)
      if (!target?.reviewRequest) throw new Error('No review was requested.')
      target.decision = structuredClone(decision)
      target.reviewRequest.status = 'complete'
    },
  }
}
