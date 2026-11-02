import { useId, useState, type FormEvent } from 'react'
import { Button, Panel, TextAreaField } from '../../components/controls'
import type { AgentContext as SavedContext, CallApi } from '../../types/callReview'

const savedAtFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'UTC',
})

export function AgentContext({
  api,
  agentId,
  conversationId,
  saved,
  onSaved,
}: {
  api: CallApi
  agentId: string
  conversationId: string
  saved: SavedContext | null
  onSaved: (context: SavedContext) => void
}) {
  const fieldId = useId()
  const [text, setText] = useState(saved?.text ?? '')
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)
  const unchanged = text.trim() === (saved?.text ?? '')

  async function save(event: FormEvent) {
    event.preventDefault()
    if (saving || !text.trim() || unchanged) return
    setSaving(true)
    setFailed(false)
    try {
      onSaved(await api.saveContext(agentId, conversationId, text))
    } catch {
      // Keep the typed text so the agent can try again.
      setFailed(true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel title="Add context" className="agent-context">
      <p>
        Explain anything the automatic feedback could not see. Saving context
        does not request a Manager review.
      </p>
      <form onSubmit={save}>
        <TextAreaField
          id={fieldId}
          label="Context for this call"
          value={text}
          onChange={(event) => setText(event.target.value)}
          disabled={saving}
        />
        {failed && (
          <p role="alert">Context could not be saved. Please try again.</p>
        )}
        {saved && !failed && (
          <p role="status" className="metadata-line">
            Saved {savedAtFormatter.format(new Date(saved.savedAt))} UTC
          </p>
        )}
        <Button
          type="submit"
          variant="secondary"
          loading={saving}
          loadingLabel="Saving…"
          disabled={!text.trim() || unchanged}
        >
          Save context
        </Button>
      </form>
    </Panel>
  )
}
