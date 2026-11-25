import { useId, useState, type FormEvent } from 'react'
import { Button, Panel, StatusLabel, TextAreaField } from '../../components/controls'
import { formatTimestamp } from '../../lib/dates'
import { useSubmission } from '../../lib/useSubmission'
import type { CallReview, CallApi } from '../../types/callReview'

const contextForm = {
  title: 'Add context',
  className: 'agent-context',
  explanation: 'Explain anything the automatic feedback could not see. Saving context does not request a Manager review.',
  field: 'Context for this call',
  action: 'Save context',
  busy: 'Saving…',
  error: 'Context could not be saved. Please try again.',
  variant: 'secondary',
} as const

const requestForm = {
  title: 'Flag feedback',
  className: 'flag-feedback',
  explanation: 'Ask a Manager to check this automatic feedback. You can flag a call once.',
  field: 'Reason for review',
  action: 'Request review',
  busy: 'Sending…',
  error: 'The review request could not be sent. Please try again.',
  variant: 'primary',
} as const

function FeedbackForm({ config, initial = '', savedAt, send }: {
  config: typeof contextForm | typeof requestForm
  initial?: string
  savedAt?: string
  send: (text: string) => Promise<void>
}) {
  const id = useId()
  const [text, setText] = useState(initial)
  const { submit, saving, failed } = useSubmission()
  const unavailable = !text.trim() || text.trim() === initial

  function save(event: FormEvent) {
    event.preventDefault()
    if (!unavailable) void submit(true, () => send(text))
  }

  return (
    <Panel title={config.title} className={config.className}>
      <p>{config.explanation}</p>
      <form onSubmit={save}>
        <TextAreaField id={id} label={config.field} value={text} disabled={Boolean(saving)}
          required={config === requestForm} onChange={(event) => setText(event.target.value)} />
        {failed && <p role="alert">{config.error}</p>}
        {savedAt && !failed && <p role="status" className="metadata-line">Saved {formatTimestamp(savedAt)}</p>}
        <Button type="submit" variant={config.variant} loading={Boolean(saving)} loadingLabel={config.busy} disabled={unavailable}>
          {config.action}
        </Button>
      </form>
    </Panel>
  )
}

export function AgentReviewForms({ api, call, findingId, update }: {
  api: CallApi
  call: CallReview
  findingId: string
  update: (changes: Partial<CallReview>) => void
}) {
  const { agentId, id, agentContext, reviewRequest } = call
  const complete = reviewRequest?.status === 'complete'
  return (
    <div className="agent-actions">
      <FeedbackForm config={contextForm} initial={agentContext?.text} savedAt={agentContext?.savedAt}
        send={async (text) => update({ agentContext: await api.saveContext(agentId, id, text) })} />
      {reviewRequest ? (
        <Panel title={requestForm.title} className={requestForm.className}>
          <StatusLabel tone={complete ? 'positive' : 'attention'}>{complete ? 'Review complete' : 'Review requested'}</StatusLabel>
          <p>
            {reviewRequest.findingId === findingId
              ? 'A Manager will check this automatic feedback.'
              : 'A Manager review has already been requested for another finding in this call.'}
          </p>
          <p className="metadata-line">Reason: {reviewRequest.reason}</p>
        </Panel>
      ) : (
        <FeedbackForm config={requestForm}
          send={async (text) => update({ reviewRequest: await api.requestReview(agentId, id, findingId, text) })} />
      )}
    </div>
  )
}
