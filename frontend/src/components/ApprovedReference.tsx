import type { KnowledgeEntry } from '../types/knowledge'
import './approved-reference.css'

function date(value: string | null) {
  if (!value) return 'Not supplied'
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00Z`)
  return Number.isNaN(parsed.getTime())
    ? 'Not supplied'
    : new Intl.DateTimeFormat('en-US', {
        dateStyle: 'medium',
        timeZone: 'UTC',
      }).format(parsed)
}

export function ApprovedReference({
  entry,
  highlightStep,
}: {
  entry: KnowledgeEntry
  highlightStep?: number | null
}) {
  return (
    <div className="approved-reference-content">
      <dl>
        <div>
          <dt>Reference</dt>
          <dd>
            {entry.id} {entry.version}
          </dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>Approved</dd>
        </div>
        <div>
          <dt>Approved</dt>
          <dd>{date(entry.approvedAt)}</dd>
        </div>
        <div>
          <dt>Approved by</dt>
          <dd>{entry.approvedBy ?? 'Not supplied'}</dd>
        </div>
        <div>
          <dt>Effective</dt>
          <dd>{date(entry.effectiveAt)}</dd>
        </div>
        <div>
          <dt>Last confirmed</dt>
          <dd>{date(entry.lastConfirmedAt)}</dd>
        </div>
        <div>
          <dt>Policy owner</dt>
          <dd>{entry.owner ?? 'Not supplied'}</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>
            {entry.source?.url ? (
              <a href={entry.source.url}>{entry.source.title}</a>
            ) : (
              (entry.source?.title ?? 'Not supplied')
            )}
          </dd>
        </div>
      </dl>
      {entry.paragraphs.map((paragraph) => (
        <p key={paragraph}>{paragraph}</p>
      ))}
      <ol>
        {entry.steps.map((step) => (
          <li
            key={step.number}
            value={step.number}
            className={
              step.number === highlightStep
                ? 'approved-reference-selected-step'
                : undefined
            }
          >
            {step.text}
          </li>
        ))}
      </ol>
    </div>
  )
}
