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
  decision: null,
}

export function createDevCallApi(): CallApi {
  return {
    async getCallForAgent(agentId, conversationId) {
      return call.agentId === agentId && call.id === conversationId
        ? structuredClone(call)
        : null
    },
  }
}
