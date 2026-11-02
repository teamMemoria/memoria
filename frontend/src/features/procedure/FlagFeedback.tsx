import { useId, useState, type FormEvent } from 'react'
import {
  Button,
  Panel,
  StatusLabel,
  TextAreaField,
} from '../../components/controls'
import type { CallApi, ReviewRequest } from '../../types/callReview'

const reviewStatus = {
  requested: { label: 'Review requested', tone: 'attention' },
  complete: { label: 'Review complete', tone: 'positive' },
} as const

export function FlagFeedback({
  api,
  agentId,
  conversationId,
  findingId,
  request,
  onRequested,
}: {
  api: CallApi
  agentId: string
  conversationId: string
  findingId: string
  request: ReviewRequest | null
  onRequested: (request: ReviewRequest) => void
}) {
  const fieldId = useId()
  const [reason, setReason] = useState('')
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState(false)

  if (request) {
    const status = reviewStatus[request.status]
    return (
      <Panel title="Flag feedback" className="flag-feedback">
        <StatusLabel tone={status.tone}>{status.label}</StatusLabel>
        <p>
          {request.findingId === findingId
            ? 'A Manager will check this automatic feedback.'
            : 'A Manager review has already been requested for another finding in this call.'}
        </p>
        <p className="metadata-line">Reason: {request.reason}</p>
      </Panel>
    )
  }

  async function send(event: FormEvent) {
    event.preventDefault()
    if (sending || !reason.trim()) return
    setSending(true)
    setFailed(false)
    try {
      onRequested(
        await api.requestReview(agentId, conversationId, findingId, reason),
      )
    } catch {
      // Keep the typed reason so the agent can try again.
      setFailed(true)
      setSending(false)
    }
  }

  return (
    <Panel title="Flag feedback" className="flag-feedback">
      <p>
        Ask a Manager to check this automatic feedback. You can flag a call
        once.
      </p>
      <form onSubmit={send}>
        <TextAreaField
          id={fieldId}
          label="Reason for review"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          disabled={sending}
          required
        />
        {failed && (
          <p role="alert">The review request could not be sent. Please try again.</p>
        )}
        <Button
          type="submit"
          loading={sending}
          loadingLabel="Sending…"
          disabled={!reason.trim()}
        >
          Request review
        </Button>
      </form>
    </Panel>
  )
}
