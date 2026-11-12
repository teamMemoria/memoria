import { useState } from 'react'
import type { ScoringCheck } from '../../types/callReview'
import { Icon } from '../../components/Icon'
import { Card } from '../../components/ui/card'
import {
  Coaching,
  ScoreCard,
  AssessmentSummary,
  EvidenceLink,
  MaterialLimits,
  EvidenceRows,
  EvidenceNotes,
} from '../assessment-shared/AssessmentElements'
import {
  checkLabels,
  checkTitle,
  checkTurns,
  featuredChecks,
  type ScreenProps,
} from '../assessment-shared/assessment'
import './answer-support.css'

export function AnswerScreen({ data, onOpen }: ScreenProps) {
  const ordered = featuredChecks(data.checks)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const featured =
    ordered.find((check) => check.id === selectedId) ?? ordered[0]
  const primary = ordered.filter(
    (check) =>
      check.critical ||
      check.outcome === 'supported' ||
      check.outcome === 'breach',
  )
  const remaining = ordered.filter((check) => !primary.includes(check))
  const claim = featured?.citations.find(
    (citation) => citation.kind === 'conversation',
  )
  const reference = featured?.citations.find(
    (citation) => citation.kind === 'reference',
  )
  const sources = featured
    ? [
        {
          title: 'Conversation evidence',
          count: featured.citations.filter(
            (c) => c.kind === 'conversation' && c.event_kind === 'message',
          ).length,
          detail: claim?.quote ?? 'Statement evidence unavailable',
          tone: 'green',
        },
        {
          title: 'Reference',
          count: featured.citations.filter((c) => c.kind === 'reference')
            .length,
          detail: reference?.quote ?? 'No eligible reference supplied',
          tone: 'blue',
        },
        {
          title: 'System record',
          count: featured.citations.filter(
            (c) => c.kind === 'conversation' && c.event_kind === 'action',
          ).length,
          detail:
            featured.citations.find(
              (c) => c.kind === 'conversation' && c.event_kind === 'action',
            )?.quote ?? 'Independent action evidence unavailable',
          tone: 'neutral',
        },
      ]
    : []
  function evidenceTable(checks: ScoringCheck[]) {
    return (
      <div
        className="source-table"
        role="table"
        aria-label={
          checks === primary
            ? 'Assessed and critical answer checks'
            : 'Unresolved and not applicable answer checks'
        }
      >
        <div role="row" className="source-table-header">
          <span role="columnheader">Check</span>
          <span role="columnheader">Evidence</span>
          <span role="columnheader">Status</span>
          <span role="columnheader">Source</span>
        </div>
        {checks.map((check) => (
          <div role="row" key={check.id}>
            <span role="cell">
              {check.critical && 'Critical · '}
              {check.requirement ===
              'Support the factual assertion and its qualifications'
                ? check.outcome === 'unresolved'
                  ? 'Unresolved factual check'
                  : 'Factual support'
                : checkTitle(check)}
              <small>
                {checkTurns(check).length
                  ? `Turn ${checkTurns(check).join(', ')}`
                  : 'No linked turn'}
              </small>
            </span>
            <p role="cell" className="check-excerpt">
              {check.citations.find(
                (citation) => citation.kind === 'conversation',
              )?.quote ?? check.explanation}
            </p>
            <span role="cell" className={`check-status--${check.outcome}`}>
              {checkLabels[check.outcome]}
            </span>
            <div role="cell">
              <EvidenceLink
                turns={checkTurns(check)}
                checkId={check.id}
                onOpen={(...selection) => {
                  setSelectedId(check.id)
                  onOpen(...selection)
                }}
              >
                View evidence
              </EvidenceLink>
            </div>
          </div>
        ))}
      </div>
    )
  }
  const groups = (Object.keys(checkLabels) as (keyof typeof checkLabels)[]).map(
    (outcome) => ({
      outcome,
      label: checkLabels[outcome],
      count: data.checks.filter((check) => check.outcome === outcome).length,
    }),
  )
  const colours = ['#16815c', '#e56c42', '#bfcbdf', '#e8ecf3']
  let offset = 0
  return (
    <>
      <section
        className="dashboard-top dashboard-top--wide"
        aria-label="Answer support checks"
      >
        <ScoreCard data={data} label="Answer support" visual="number" />
        <Card className="dashboard-card action-area source-coverage">
          <h2>Agent actions</h2>
          {!data.criterion?.scoring && (
            <AssessmentSummary data={data} onOpen={onOpen} />
          )}
          <div className="answer-visuals">
            <div className="claim-chart-layout">
              <div
                className="claim-donut"
                role="img"
                aria-label={`Recorded checks: ${groups.map((g) => `${g.count} ${g.label.toLowerCase()}`).join(', ')}`}
              >
                <svg viewBox="0 0 200 200" aria-hidden="true">
                  <circle
                    className="distribution-track"
                    cx="100"
                    cy="100"
                    r="83"
                  />
                  {groups.map((group, index) => {
                    // Distribution of stored check outcomes, never a score or claim estimate.
                    const length = data.checks.length
                      ? (100 * group.count) / data.checks.length
                      : 0
                    const start = offset
                    offset += length
                    return (
                      length > 0 && (
                        <circle
                          key={group.outcome}
                          className="distribution-value"
                          cx="100"
                          cy="100"
                          r="83"
                          pathLength="100"
                          stroke={colours[index]}
                          strokeDasharray={`${length} ${100 - length}`}
                          strokeDashoffset={-start}
                        />
                      )
                    )
                  })}
                </svg>
                <div className="donut-center">
                  <strong>{data.checks.length || '—'}</strong>
                  <span>recorded checks</span>
                </div>
              </div>
              <ul className="check-legend">
                {groups
                  .filter((g) => g.count)
                  .map((g) => (
                    <li key={g.outcome}>
                      <i style={{ background: colours[groups.indexOf(g)] }} />
                      <span>{g.label}</span>
                      <strong>{g.count}</strong>
                    </li>
                  ))}
              </ul>
            </div>
            <div className="coverage-rows">
              <p className="source-scope">
                Sources for selected check
                <br />
                <strong>
                  {featured
                    ? `${checkTitle(featured)}${checkTurns(featured).length ? ` · Turn ${checkTurns(featured).join(', ')}` : ''}`
                    : 'No check selected'}
                </strong>
              </p>
              {sources.map((source) => (
                <button
                  key={source.title}
                  className={`coverage-row coverage-row--${source.tone}`}
                  onClick={(event) => {
                    event.currentTarget.focus()
                    onOpen(
                      checkTurns(featured!),
                      undefined,
                      undefined,
                      featured!.id,
                    )
                  }}
                >
                  <span className="coverage-label">
                    <strong>{source.title}</strong>
                    <span>
                      {source.count ? `${source.count} cited` : 'Unavailable'}
                    </span>
                  </span>
                  <span className="coverage-track" aria-hidden="true">
                    <i style={{ width: source.count ? '100%' : '0%' }} />
                  </span>
                  <span className="coverage-detail">
                    <span className="check-excerpt">{source.detail}</span>
                    <Icon name="arrowRight" size={14} />
                  </span>
                </button>
              ))}
            </div>
          </div>
          {featured && (
            <>
              <p className="quiet-note">{featured.explanation}</p>
              <EvidenceLink
                turns={checkTurns(featured)}
                checkId={featured.id}
                onOpen={onOpen}
              >
                Compare with source
              </EvidenceLink>
            </>
          )}
        </Card>
      </section>
      <Card className="dashboard-card evidence-section">
        <div className="section-heading">
          <h2>Evidence</h2>
          <span className="reference-tag">Recorded factual checks</span>
        </div>
        {primary.length ? (
          evidenceTable(primary)
        ) : (
          <p className="quiet-note">No resolved factual checks supplied.</p>
        )}
        {remaining.length > 0 && (
          <details className="remaining-checks">
            <summary>
              {
                remaining.filter((check) => check.outcome === 'unresolved')
                  .length
              }{' '}
              unresolved ·{' '}
              {
                remaining.filter((check) => check.outcome === 'not-applicable')
                  .length
              }{' '}
              not applicable
            </summary>
            <p>
              Retained checks outside the assessed score. Open a row to inspect
              its evidence and limitations.
            </p>
            {evidenceTable(remaining)}
          </details>
        )}
        {!data.criterion?.scoring ? (
          <EvidenceRows data={data} onOpen={onOpen} />
        ) : (
          <EvidenceNotes data={data} />
        )}
        {!data.checks.length && (
          <p className="quiet-note">Individual factual checks unavailable.</p>
        )}
        <MaterialLimits data={data} />
      </Card>
      <Coaching data={data} />
    </>
  )
}
