import type { CallReview } from '../types/callReview'

export function TranscriptNotice({ transcript, className, managerReview = false }: {
  transcript: CallReview['transcript']
  className: string
  managerReview?: boolean
}) {
  if (transcript?.complete) return null
  const message = managerReview
    ? transcript?.unavailableReason ?? 'The complete conversation is unavailable.'
    : transcript?.unavailableReason || 'The complete transcript is unavailable.'
  return (
    <p className={className}>
      {message}{' '}
      Missing evidence does not establish an {managerReview ? 'agent' : 'Agent'} error.
    </p>
  )
}
