import { useId, useState, type FormEvent } from 'react'
import { Button, TextAreaField, TextField } from '../../components/controls'
import type { KnowledgeDraftContent } from '../../types/knowledge'

function draftContent(form: HTMLFormElement): KnowledgeDraftContent {
  const fields = new FormData(form)
  return {
    title: String(fields.get('title') ?? '').trim(),
    question: String(fields.get('question') ?? '').trim(),
    guidance: String(fields.get('guidance') ?? '').trim(),
  }
}

export function KnowledgeDraftEditor({ initial, onPreview, onSave, onCancel }: {
  initial: KnowledgeDraftContent
  onPreview: (content: KnowledgeDraftContent) => void
  onSave: (content: KnowledgeDraftContent) => Promise<void>
  onCancel: () => void
}) {
  const id = useId()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (saving) return
    const content = draftContent(event.currentTarget)
    if (!content.title || !content.question || !content.guidance) {
      setError('Enter a title, question, and guidance.')
      return
    }
    if (content.title === initial.title && content.question === initial.question && content.guidance === initial.guidance) {
      onCancel()
      return
    }
    setSaving(true)
    setError('')
    try {
      await onSave(content)
    } catch {
      setError('Could not save this draft. Copy your edits before reloading the latest version.')
      setSaving(false)
    }
  }

  return (
    <form className="knowledge-draft-editor" aria-labelledby={id}
      onChange={(event) => onPreview(draftContent(event.currentTarget))} onSubmit={save}>
      <h3 id={id}>Edit draft</h3>
      <TextField id={`${id}-title`} name="title" label="Title" required maxLength={140} defaultValue={initial.title} disabled={saving} />
      <TextAreaField id={`${id}-question`} name="question" label="Question" required rows={3} maxLength={600} defaultValue={initial.question} disabled={saving} />
      <TextAreaField id={`${id}-guidance`} name="guidance" label="Guidance" required rows={9} maxLength={5000} defaultValue={initial.guidance} disabled={saving} />
      {error && <p role="alert">{error}</p>}
      <div className="knowledge-review-actions">
        <Button variant="secondary" onClick={onCancel} disabled={saving}>Cancel</Button>
        <Button type="submit" loading={saving} loadingLabel="Saving…" disabled={saving}>Save draft</Button>
      </div>
    </form>
  )
}
