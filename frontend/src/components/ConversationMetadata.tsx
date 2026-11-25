import type { CallReview } from '../types/callReview'

export function ConversationMetadata({ call, sourceId }: {
  call: CallReview
  sourceId: string | null | undefined
}) {
  const transcript = call.transcript
  const count = transcript?.turns.length ?? 0
  return (
    <ul className="call-overview-metadata" aria-label="Call details">
      <li>
        {call.assessmentSource === 'simulation'
          ? `ABCD ${sourceId}`
          : `Call ${call.id}${sourceId ? ` (ABCD ${sourceId})` : ''}`}
      </li>
      <li>{call.agentName}</li>
      <li>
        {transcript
          ? `${count} ${transcript.complete ? '' : 'recorded '}${count === 1 ? 'turn' : 'turns'}`
          : 'Turns unavailable'}
      </li>
    </ul>
  )
}
