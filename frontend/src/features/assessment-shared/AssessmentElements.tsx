import { TranscriptNotice } from '../../components/TranscriptNotice'
import type { ReactNode } from 'react'
import { Card } from '../../components/ui/card'
import { Icon } from '../../components/Icon'
import { StatusLabel } from '../../components/controls'
import {
  auditResults,
  assessmentPercentage,
  hasMidpointScoring,
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
      className="source-link inline-center"
      onClick={(event) => {
        event.currentTarget.focus()
        onOpen(turns, referenceId, section, checkId)
      }}
    >
      <span>{children}</span>
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

const dashboards = {
  procedure: { label: 'Procedure checks', score: 'Procedure checks', visual: 'half', layout: 'three procedure-top' },
  'answer-support': { label: 'Answer support checks', score: 'Answer support', visual: 'number', layout: 'wide' },
  completeness: { label: 'Request completeness checks', score: 'Requests', visual: 'ring', layout: 'wide' },
  'communication-style': { label: 'Communication wording checks', score: 'Clarity & respect', visual: 'wording', layout: 'three communication-top' },
} as const

export function AssessmentDashboard({ data, category, children }: {
  data: AssessmentData
  category: keyof typeof dashboards
  children: ReactNode
}) {
  const { label, score, visual, layout } = dashboards[category]
  return (
    <section className={`dashboard-top dashboard-top--${layout}`} aria-label={label}>
      <ScoreCard data={data} label={score} visual={visual} />
      {children}
    </section>
  )
}

function ScoreCard({
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
  const simulation = data.call.assessmentSource === 'simulation'
  const available =
    !scoring?.processingError && scoring?.score != null && (simulation || scoring.coverage !== 0)
  const scoreLabel = scoring?.processingError
    ? 'Processing error'
    : scoring
      ? simulation ? percentage(scoring.score) : assessmentPercentage(scoring)
      : 'Score unavailable'
  const scoreText = available ? percentage(scoring!.score) : '—'
  return (
    <Card
      className={`dashboard-card score-area flex-center ${visual === 'wording' ? 'score-area--wording' : ''} ${available ? '' : 'score-area--unavailable'}`}
    >
      <div className="card-eyebrow flex-center">{label}</div>
      <div className="score-measurement flex-center">
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
            <svg viewBox={visual === 'half' ? '0 0 240 152' : '0 0 200 200'} aria-hidden="true">
              <GaugeShape half={visual === 'half'} />
              {available && <GaugeShape half={visual === 'half'} score={scoring!.score!} />}
            </svg>
            <div className="gauge-copy flex-center">
              <strong>{scoreText}</strong>
              {!available && <span>{scoreLabel}</span>}
            </div>
          </div>
        )}
        {((available && !simulation) || (!available && visual === 'number')) && (
          <p className="score-description">
            {!available ? scoreLabel : hasMidpointScoring(data.call.assessmentVersion?.scoringMethod)
              ? 'Includes half the unresolved points.'
              : 'of assessed points'}
          </p>
        )}
        {!simulation && !scoring && result && (
          <StatusLabel tone={result.tone}>{result.label}</StatusLabel>
        )}
        <p className="score-description">
          {scoring
            ? `Evidence coverage: ${percentage(scoring.coverage, 'Unknown')}`
            : 'Check totals unavailable.'}
        </p>
      </div>
    </Card>
  )
}

function GaugeShape({ half, score }: { half: boolean; score?: number }) {
  const sweep = score === undefined ? {} : { pathLength: 100, strokeDasharray: `${score} 100` }
  const className = score === undefined ? 'gauge-track' : half ? 'gauge-value' : 'gauge-value gauge-value--circle'
  return half
    ? <path className={className} d="M24 126 A96 96 0 0 1 216 126" {...sweep} />
    : <circle className={className} cx="100" cy="100" r="83" {...sweep} />
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
      <figcaption className="assessment-metadata">
        <span>{turn.speaker}</span>
        <span>Turn {turn.number}</span>
        {turn.time && <span>{turn.time}</span>}
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
  return (
    <>
      <p className="card-subtitle">
        {data.criterion?.explanation ??
          'This category’s assessment is unavailable.'}
      </p>
      {data.findings.map((finding) => (
        <section className="recorded-finding" key={finding.id}>
          <h3>
            {finding.title}
            {finding.critical && ' (critical)'}
          </h3>
          <p>{finding.explanation}</p>
          <ItemEvidence item={finding} onOpen={onOpen} />
        </section>
      ))}
    </>
  )
}

export function MoreChecks({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <details className={`more-checks ${className}`}>
      <summary className="more-checks-toggle" aria-label="Additional checks" title="Additional checks">
        <Icon name="chevronDown" size={20} />
      </summary>
      {children}
    </details>
  )
}

export function CheckList({
  checks,
  onOpen,
  showExplanations = true,
}: {
  checks: ScoringCheck[]
  onOpen: EvidenceHandler
  showExplanations?: boolean
}) {
  const ordered = featuredChecks(checks)
  const visible = Math.max(3, ordered.filter((check) => check.critical).length)
  const row = (check: ScoringCheck) => (
    <button
      key={check.id}
      className={`check-row flex-center check-row--${check.outcome === 'breach' ? 'attention' : check.outcome}`}
      onClick={(event) => {
        event.currentTarget.focus()
        onOpen(checkTurns(check), undefined, undefined, check.id)
      }}
    >
      <span className="check-symbol grid-center grid-center">
        <Icon
          name={check.outcome === 'supported' ? 'check' : 'info'}
          size={17}
        />
      </span>
      <span>
        <strong>
          {checkTitle(check)}
          {check.critical && ' (critical)'}
        </strong>
        {showExplanations && <small className="check-excerpt">{check.explanation}</small>}
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
        <MoreChecks>{ordered.slice(visible).map(row)}</MoreChecks>
      )}
      {!checks.length && (
        <p className="card-subtitle">No individual checks supplied.</p>
      )}
    </div>
  )
}

export function EvidenceSection({ data, titleId, action, children, afterNotes }: {
  data: AssessmentData
  titleId: string
  action?: ReactNode
  children: ReactNode
  afterNotes?: ReactNode
}) {
  return (
    <section className="evidence-section evidence-section--plain" aria-labelledby={titleId}>
      <div className="section-heading flex-center">
        <h2 id={titleId}>Evidence</h2>
        {action}
      </div>
      {children}
      <EvidenceNotes data={data} />
      {afterNotes}
      <MaterialLimits data={data} />
    </section>
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
                {turn.time ? ` (${turn.time})` : ''}
              </small>
            </span>
            <p className="check-excerpt">{turn.text}</p>
            <EvidenceLink turns={[turn.number]} onOpen={onOpen}>
              View turn {turn.number}
            </EvidenceLink>
          </div>
        ))}
      </div>
    </>
  )
}

export function MaterialLimits({ data }: { data: AssessmentData }) {
  const scoring = data.criterion?.scoring
  if (!scoring) return null
  if (scoring.processingError)
    return (
      <p role="alert" className="quiet-note flex-center">
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
            <strong>{check.requirement} (critical)</strong> {check.explanation}
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
  if (data.call.assessmentSource === 'simulation' && !suggestions.length) return null

  return (
    <CoachingNotice title="How to improve" empty={!suggestions.length}>
      {!suggestions.length && <p>No recommendation recorded.</p>}
      {suggestions.map((finding) => <p key={finding.id}>{finding.suggestion}</p>)}
    </CoachingNotice>
  )
}

export function CoachingNotice({ title, label = title, empty, children }: {
  title: string; label?: string; empty?: boolean; children: ReactNode
}) {
  return (
    <section className={`coaching ${empty ? 'coaching--empty' : ''}`} aria-label={label}>
      <div className="coaching-summary">
        <span className="coaching-icon grid-center"><Icon name="info" size={23} /></span>
        <div><h2>{title}</h2>{children}</div>
      </div>
    </section>
  )
}

export function EvidenceNotes({ data }: { data: AssessmentData }) {
  return (
    <>
      <TranscriptNotice transcript={data.call.transcript} className="quiet-note flex-center" />
      {data.missingTurns.length > 0 && (
        <p className="quiet-note flex-center">
          Cited passages unavailable: {data.missingTurns.join(', ')}.
        </p>
      )}
      {!data.turns.length && (
        <p className="quiet-note flex-center">
          No transcript passages are linked to this category.
        </p>
      )}
    </>
  )
}
