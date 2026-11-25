import { useId, useState, type CSSProperties, type ReactNode } from 'react'
import { Button } from '../../components/controls'

export function KnowledgeDocument({ title, question, children, onEdit, editor }: {
  title: string
  question: string
  children: ReactNode
  onEdit?: () => void
  editor?: ReactNode
}) {
  const questionId = useId()
  const [zoom, setZoom] = useState('1')

  return (
    <section className="knowledge-document" aria-label="Draft document viewer">
      <div className="knowledge-document-toolbar">
        <select aria-label="Document zoom" value={zoom} onChange={(event) => setZoom(event.target.value)}>
          <option value="0.75">75%</option>
          <option value="1">Fit width</option>
          <option value="1.25">125%</option>
        </select>
        <Button variant="secondary" disabled={Boolean(editor)} onClick={() => window.print()}>Print / Save PDF</Button>
        {onEdit && !editor && <Button onClick={onEdit}>Edit draft</Button>}
      </div>
      <div className="knowledge-document-body">
        <div className="knowledge-document-viewport" role="region" aria-label="Document preview" tabIndex={0}>
          <article className="knowledge-document-paper" aria-labelledby={questionId}
            style={{ '--document-zoom': zoom } as CSSProperties}>
            <div className="knowledge-document-title">{title}</div>
            <h2 id={questionId}>{question}</h2>
            {children}
          </article>
        </div>
        {editor}
      </div>
    </section>
  )
}
