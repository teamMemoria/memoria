import type { ReactNode } from 'react'
import { Card } from '../../components/ui/card'
import { Icon } from '../../components/Icon'
import { StatusLabel } from '../../components/controls'
import {
  auditResults,
  percentage,
  type TranscriptTurn,
  type ScoringCheck,
} from '../../types/callReview'
import type {
  AssessmentData,
  EvidenceHandler,
  EvidenceItem,
} from './assessment'
import {
  checkLabels,
  featuredChecks,
  checkTitle,
  checkTurns,
} from './assessment'
export type { EvidenceHandler } from './assessment'

export function EvidenceLink({
  turns,
  referenceId,
  section,
  children,
  checkId,
  onOpen,
}: {
  turns: number[]
  referenceId?: string | null
  section?: number | null
  children: ReactNode
  checkId?: string
  onOpen: EvidenceHandler
}) {
  return (
    <button
      className="source-link"
      onClick={(event) => {
        event.currentTarget.focus()
        onOpen(turns, referenceId, section, checkId)
      }}
    >
      <span>{children}</span>
      <Icon name="arrowRight" size={15} />
    </button>
  )
}

export function ItemEvidence({
  item,
  onOpen,
}: {
  item: EvidenceItem
  onOpen: EvidenceHandler
}) {
  return item.evidenceTurnNumbers.length || item.referenceId ? (
    <EvidenceLink
      turns={item.evidenceTurnNumbers}
      referenceId={item.referenceId}
      section={item.referenceStep}
      onOpen={onOpen}
    >
      View evidence
    </EvidenceLink>
  ) : (
    <p className="text-muted">No linked evidence supplied.</p>
  )
}

export function ScoreCard({
  data,
  label,
  visual = 'ring',
}: {
  data: AssessmentData
  label: string
  visual?: 'half' | 'ring' | 'number' | 'wording'
}) {
  const result = data.criterion && auditResults[data.criterion.result]
  const scoring = data.criterion?.scoring
  const available = !scoring?.processingError && scoring?.score != null
  const scoreLabel = scoring?.processingError
    ? 'Processing error'
    : scoring
      ? percentage(scoring.score)
      : 'Score unavailable'
  const scoreText = available ? percentage(scoring!.score) : '—'
  return (
    <Card
      className={`dashboard-card score-area ${visual === 'wording' ? 'score-area--wording' : ''} ${available ? '' : 'score-area--unavailable'}`}
    >
      <div className="card-eyebrow">
        {label}
        {visual === 'wording' && <span className="card-badge">Text only</span>}
      </div>
      <div className="score-measurement">
        {visual === 'number' ? (
          <div className="big-score">
            <span aria-label={scoreLabel}>{scoreText}</span>
          </div>
        ) : (
          <div
            className={`metric-gauge ${visual === 'half' ? 'metric-gauge--half' : ''} ${visual === 'wording' ? 'metric-gauge--wording' : ''}`}
            role="img"
            aria-label={scoreLabel}
          >
            {visual === 'half' ? (
              <svg viewBox="0 0 240 152" aria-hidden="true">
                <path
                  className="gauge-track"
                  d="M24 126 A96 96 0 0 1 216 126"
                />
                {available && (
                  <path
                    className="gauge-value"
                    pathLength="100"
                    strokeDasharray={`${scoring!.score} 100`}
                    d="M24 126 A96 96 0 0 1 216 126"
                  />
                )}
              </svg>
            ) : (
              <svg viewBox="0 0 200 200" aria-hidden="true">
                <circle className="gauge-track" cx="100" cy="100" r="83" />
                {available && (
                  <circle
                    className="gauge-value gauge-value--circle"
                    pathLength="100"
                    strokeDasharray={`${scoring!.score} 100`}
                    cx="100"
                    cy="100"
                    r="83"
                  />
                )}
              </svg>
            )}
            <div className="gauge-copy">
              <strong>{scoreText}</strong>
              {!available && <span>{scoreLabel}</span>}
            </div>
          </div>
        )}
        {(available || visual === 'number') && (
          <p className="score-description">
            {!available ? scoreLabel : 'of assessed points'}
          </p>
        )}
        {!scoring && result && (
          <StatusLabel tone={result.tone}>{result.label}</StatusLabel>
        )}
        <p className="score-description">
          {scoring
            ? `Evidence coverage: ${percentage(scoring.coverage, 'Unknown')}`
            : 'Check totals unavailable.'}
        </p>
      </div>
      <div className="score-footer">
        <span>
          Assessed points
          <strong>
            {scoring?.assessable ?? '—'} / {scoring?.possible ?? '—'}
          </strong>
        </span>
        <span>
          Unresolved checks
          <strong>
            {scoring
              ? data.checks.filter((check) => check.outcome === 'unresolved')
                  .length
              : '—'}
          </strong>
        </span>
      </div>
    </Card>
  )
}

export function Quote({
  turn,
  onOpen,
}: {
  turn: TranscriptTurn
  onOpen: EvidenceHandler
}) {
  return (
    <figure className="inline-quote">
      <figcaption>
        {turn.speaker} · Turn {turn.number}
        {turn.time ? ` · ${turn.time}` : ''}
      </figcaption>
      <blockquote>{turn.text}</blockquote>
      <EvidenceLink turns={[turn.number]} onOpen={onOpen}>
        View turn {turn.number}
      </EvidenceLink>
    </figure>
  )
}

export function AssessmentSummary({
  data,
  onOpen,
}: {
  data: AssessmentData
  onOpen: EvidenceHandler
}) {
  const check = featuredChecks(data.checks)[0]
  if (check)
    return (
      <>
        <h2>
          {check.critical && 'Critical · '}
          {checkTitle(check)}
        </h2>
        <p className="card-subtitle">{check.explanation}</p>
        <CheckEvidence check={check} onOpen={onOpen} />
      </>
    )
  return (
    <>
      <p className="card-subtitle">
        {data.criterion?.explanation ??
          'This category’s assessment is unavailable.'}
      </p>
      {data.findings.map((finding) => (
        <section className="recorded-finding" key={finding.id}>
          <h3>
            {finding.critical && 'Critical · '}
            {finding.title}
          </h3>
          <p>{finding.explanation}</p>
          <ItemEvidence item={finding} onOpen={onOpen} />
        </section>
      ))}
    </>
  )
}

// Canonical citation text stays intact; the evidence sheet supplies surrounding turns.
export function CheckEvidence({
  check,
  onOpen,
  expanded,
}: {
  check: ScoringCheck
  onOpen: EvidenceHandler
  expanded?: boolean
}) {
  return (
    <details className="check-evidence" open={expanded}>
      <summary>Evidence & details</summary>
      <h3>{check.requirement}</h3>
      <p>{check.explanation}</p>
      {check.advice && <p>{check.advice}</p>}
      <p>
        {check.earned == null
          ? 'Unscored'
          : `${check.earned}/${check.maximum} points`}{' '}
        · {checkLabels[check.outcome]}
      </p>
      {check.citations.map((citation, index) => (
        <figure key={index} className="source-quote">
          <blockquote>{citation.quote}</blockquote>
          <figcaption>
            {citation.kind === 'conversation' ? (
              <>
                <EvidenceLink turns={[citation.turn_id]} onOpen={onOpen}>
                  Turn {citation.turn_id} · {citation.event_kind}
                </EvidenceLink>
                <details className="source-provenance">
                  <summary>Source version</summary>
                  <small>
                    Source {citation.conversation_id} ·{' '}
                    {citation.transcript_version}
                  </small>
                </details>
              </>
            ) : (
              <>
                <span>
                  Guideline/rubric section {citation.section_id} ·{' '}
                  {citation.reference_id}
                </span>
                <details className="source-provenance">
                  <summary>Reference version and eligibility</summary>
                  <small>
                    {citation.reference_version} · eligible at the recorded
                    assessment date
                  </small>
                </details>
              </>
            )}
          </figcaption>
        </figure>
      ))}
      {!check.citations.length && <p>No linked evidence supplied.</p>}
    </details>
  )
}

export function CheckList({
  checks,
  onOpen,
}: {
  checks: ScoringCheck[]
  onOpen: EvidenceHandler
}) {
  const ordered = featuredChecks(checks)
  const visible = Math.max(3, ordered.filter((check) => check.critical).length)
  const row = (check: ScoringCheck) => (
    <button
      key={check.id}
      className={`check-row check-row--${check.outcome === 'breach' ? 'attention' : check.outcome}`}
      onClick={(event) => {
        event.currentTarget.focus()
        onOpen(checkTurns(check), undefined, undefined, check.id)
      }}
    >
      <span className="check-symbol">
        <Icon
          name={check.outcome === 'supported' ? 'check' : 'info'}
          size={17}
        />
      </span>
      <span>
        <strong>
          {check.critical && 'Critical · '}
          {checkTitle(check)}
        </strong>
        <small className="check-excerpt">{check.explanation}</small>
      </span>
      <span
        className={`mini-status ${check.outcome === 'breach' ? 'mini-status--attention' : check.outcome === 'supported' ? '' : 'mini-status--neutral'}`}
      >
        {checkLabels[check.outcome]}
      </span>
    </button>
  )
  return (
    <div className="procedure-checks">
      {ordered.slice(0, visible).map(row)}
      {ordered.length > visible && (
        <details className="more-checks">
          <summary>
            All {ordered.length} checks ·{' '}
            {ordered.filter((check) => check.outcome === 'unresolved').length}{' '}
            unresolved
          </summary>
          {ordered.slice(visible).map(row)}
        </details>
      )}
      {!checks.length && (
        <p className="card-subtitle">No individual checks supplied.</p>
      )}
    </div>
  )
}

export function EvidenceRows({
  data,
  onOpen,
}: {
  data: AssessmentData
  onOpen: EvidenceHandler
}) {
  return (
    <>
      <div className="evidence-rows">
        {data.turns.map((turn) => (
          <div className="evidence-row" key={turn.number}>
            <span className="evidence-position">
              Turn {turn.number}
              <small>
                {turn.speaker}
                {turn.time ? ` · ${turn.time}` : ''}
              </small>
            </span>
            <p className="check-excerpt">{turn.text}</p>
            <EvidenceLink turns={[turn.number]} onOpen={onOpen}>
              View turn {turn.number}
            </EvidenceLink>
          </div>
        ))}
      </div>
      <EvidenceNotes data={data} />
    </>
  )
}

export function MaterialLimits({ data }: { data: AssessmentData }) {
  const scoring = data.criterion?.scoring
  if (!scoring) return null
  if (scoring.processingError)
    return (
      <p role="alert" className="quiet-note">
        Processing error: {scoring.processingError}. This is not an Agent
        performance result.
      </p>
    )
  const limits = [...new Set(scoring.limitations)]
  return (
    <>
      {data.checks
        .filter((check) => check.critical)
        .map((check) => (
          <p key={check.id} className="critical-check">
            <strong>Critical · {check.requirement}</strong> {check.explanation}
          </p>
        ))}
      {limits.length > 0 && (
        <aside
          className="assessment-limits"
          aria-label="Assessment limitations"
        >
          <strong>Unresolved</strong>
          <ul>
            {limits.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </aside>
      )}
    </>
  )
}

export function Coaching({ data }: { data: AssessmentData }) {
  const suggestions = data.findings.filter((finding) =>
    finding.suggestion.trim(),
  )

  return (
    <section
      className={`coaching ${suggestions.length ? '' : 'coaching--empty'}`}
      aria-label="How to improve"
    >
      <div className="coaching-summary">
        <span className="coaching-icon">
          <Icon name="info" size={23} />
        </span>
        <div>
          <h2>How to improve</h2>
          {!suggestions.length && <p>No recommendation recorded.</p>}
          {suggestions.map((finding) => (
            <p key={finding.id}>{finding.suggestion}</p>
          ))}
        </div>
      </div>
    </section>
  )
}

export function EvidenceNotes({ data }: { data: AssessmentData }) {
  return (
    <>
      {!data.call.transcript?.complete && (
        <p className="quiet-note">
          {data.call.transcript?.unavailableReason ||
            'The complete transcript is unavailable.'}{' '}
          Missing evidence does not establish an Agent error.
        </p>
      )}
      {data.missingTurns.length > 0 && (
        <p className="quiet-note">
          Cited passages unavailable: {data.missingTurns.join(', ')}.
        </p>
      )}
      {!data.turns.length && (
        <p className="quiet-note">
          No transcript passages are linked to this category.
        </p>
      )}
    </>
  )
}
