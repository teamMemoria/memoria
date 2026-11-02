import { StatusLabel } from '../../components/controls'
import type { KnowledgeEntry } from '../../types/knowledge'
import { formatKnowledgeDate } from './knowledge'

const refundStepHeadings: Record<number, string> = {
  1: 'Identify the customer.',
  2: 'Verify the purchase.',
  3: 'Agree on the refund method.',
  4: 'Submit and confirm.',
}

export function KnowledgeArticleContent({ entry }: { entry: KnowledgeEntry }) {
  const isRefundProcedure =
    entry.kind === 'procedure' && entry.id === 'RP-01' && entry.version === 'v1'
  const details = [
    { label: 'Reference', value: `${entry.id} ${entry.version}` },
    { label: 'Approved', value: formatKnowledgeDate(entry.approvedAt) },
    { label: 'Effective', value: formatKnowledgeDate(entry.effectiveAt) },
    { label: 'Policy owner', value: entry.owner ?? 'Not supplied' },
    {
      label: 'Source',
      value: entry.source?.url ? (
        <a href={entry.source.url}>{entry.source.title}</a>
      ) : (
        (entry.source?.title ?? 'Not supplied')
      ),
    },
    { label: 'Approved by', value: entry.approvedBy ?? 'Not supplied' },
    {
      label: 'Last confirmed',
      value: formatKnowledgeDate(entry.lastConfirmedAt),
    },
  ]

  return (
    <section
      className="knowledge-article"
      aria-labelledby="knowledge-article-title"
    >
      <header className="knowledge-article-header">
        <div className="knowledge-article-title-row">
          <h1 id="knowledge-article-title">{entry.title}</h1>
          <StatusLabel tone="positive">Approved</StatusLabel>
        </div>
        <div className="knowledge-article-subtitle">
          <span>
            {entry.id} {entry.version}
          </span>
          <p>Read-only approved guidance.</p>
        </div>
      </header>
      <div
        className="knowledge-article-body"
        role="region"
        aria-label="Approved guidance content"
      >
        {entry.paragraphs.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
        {entry.steps.length > 0 && (
          <ol
            className="knowledge-procedure"
            role="list"
            aria-label="Procedure steps"
          >
            {entry.steps.map((step) => {
              const heading = isRefundProcedure
                ? refundStepHeadings[step.number]
                : undefined
              const phrase = 'before offering a refund.'
              const emphasisIndex =
                isRefundProcedure && step.number === 2
                  ? step.text.indexOf(phrase)
                  : -1
              return (
                <li
                  key={step.number}
                  value={step.number}
                  className={`knowledge-procedure-step${emphasisIndex >= 0 ? ' knowledge-procedure-step--emphasis' : ''}`}
                >
                  <span className="knowledge-step-number" aria-hidden="true">
                    {String(step.number).padStart(2, '0')}
                  </span>
                  <div className="knowledge-step-content">
                    {heading && <h2>{heading}</h2>}
                    {step.text !== heading && (
                      <p>
                        {emphasisIndex >= 0 ? (
                          <>
                            {step.text.slice(0, emphasisIndex)}
                            <strong className="knowledge-procedure-rule">
                              {phrase}
                            </strong>
                            {step.text.slice(emphasisIndex + phrase.length)}
                          </>
                        ) : (
                          step.text
                        )}
                      </p>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </div>
      <aside
        className="knowledge-reference"
        aria-labelledby="knowledge-reference-title"
      >
        <h2 id="knowledge-reference-title">Reference details</h2>
        <dl>
          {details.map(({ label, value }) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </aside>
    </section>
  )
}
