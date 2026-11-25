import type { CallReview } from '../types/callReview'

export function ConversationMetadata({ call, sourceId, showTopic = false }: {
  call: CallReview
  sourceId: string | null | undefined
  showTopic?: boolean
}) {
  const transcript = call.transcript
  const count = transcript?.turns.length ?? 0
  const callLabel = call.assessmentSource === 'simulation'
    ? `ABCD ${sourceId}`
    : `Call ${call.id}${sourceId ? ` (ABCD ${sourceId})` : ''}`
  return (
    <ul className="call-overview-metadata" aria-label="Call details">
      <li>{showTopic ? call.topic : callLabel}</li>
      <li>{call.agentName}</li>
      <li>
        {transcript
          ? `${count} ${transcript.complete ? '' : 'recorded '}${count === 1 ? 'turn' : 'turns'}`
          : 'Turns unavailable'}
      </li>
    </ul>
  )
}
