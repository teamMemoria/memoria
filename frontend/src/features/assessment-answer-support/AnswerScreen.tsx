import { useAnswer } from './controller'
import { answerEvidencePreview } from './presenter'
import type { ScoringCheck } from '../../types/callReview'
import { Card } from '../../components/ui/card'
import {
  Coaching,
  AssessmentDashboard,
  AssessmentSummary,
  EvidenceLink,
  EvidenceRows,
  EvidenceSection,
  MoreChecks,
} from '../assessment-shared/AssessmentElements'
import {
  checkLabels,
  checkTitle,
  checkTurns,
  type ScreenProps,
} from '../assessment-shared/assessment'
import './answer-support.css'

export function AnswerScreen({ data, onOpen }: ScreenProps) {
  const { featured, primary, remaining, sources, summary, setSelectedId } = useAnswer(data)
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
              <span className="check-excerpt">
                {checkTitle(check)}
                {check.critical && ' (critical)'}
              </span>
            </span>
            <p role="cell" className="check-excerpt">
              {answerEvidencePreview(check)}
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
  ).filter((group) => group.outcome !== 'partial' || group.count > 0)
  const colours = { supported: '#16815c', partial: '#4569b5', breach: '#e56c42', unresolved: '#bfcbdf', 'not-applicable': '#e8ecf3' }
  let offset = 0
  return (
    <>
      <AssessmentDashboard data={data} category="answer-support">
        <Card className="dashboard-card action-area">
          <h2>Answer checks</h2>
          {!data.criterion?.scoring && (
            <AssessmentSummary data={data} onOpen={onOpen} />
          )}
          <div className="answer-visuals">
            <div className="claim-chart-layout flex-center">
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
                  {groups.map((group) => {
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
                          stroke={colours[group.outcome]}
                          strokeDasharray={`${length} ${100 - length}`}
                          strokeDashoffset={-start}
                        />
                      )
                    )
                  })}
                </svg>
                <div className="donut-center flex-center">
                  <strong>{data.checks.length || '—'}</strong>
                  <span>{data.checks.length === 1 ? 'check' : 'checks'}</span>
                </div>
              </div>
              <ul className="check-legend">
                {groups
                  .filter((g) => g.count)
                  .map((g) => (
                    <li key={g.outcome}>
                      <i style={{ background: colours[g.outcome] }} />
                      <span>{g.label}</span>
                      <strong>{g.count}</strong>
                    </li>
                  ))}
              </ul>
            </div>
            {featured && (
              <div className="answer-selected-check">
                <div className="source-scope">
                  <h3>{checkTitle(featured)}</h3>
                  <span className={`card-badge inline-center answer-status--${featured.outcome}`}>
                    {checkLabels[featured.outcome]}
                  </span>
                </div>
                {summary && <p className="answer-check-summary">{summary}</p>}
                <div className="answer-sources">
                  {sources.map((source) => (
                    <button
                      key={source.title}
                      className="answer-source"
                      onClick={(event) => {
                        event.currentTarget.focus()
                        onOpen(checkTurns(featured), undefined, undefined, featured.id)
                      }}
                    >
                      <span className="answer-source-heading">
                        <strong>{source.title}</strong>
                        <span>{source.count ? `${source.count} cited` : 'Unavailable'}</span>
                      </span>
                      <span className="check-excerpt">{source.detail}</span>
                    </button>
                  ))}
                </div>
                <EvidenceLink turns={checkTurns(featured)} checkId={featured.id} onOpen={onOpen}>
                  Compare with source
                </EvidenceLink>
              </div>
            )}
          </div>
        </Card>
      </AssessmentDashboard>
      <EvidenceSection
        titleId="answer-evidence-title"
        data={data}
        action={<span className="reference-tag inline-center">Recorded factual checks</span>}
        afterNotes={!data.checks.length && <p className="quiet-note flex-center">Individual factual checks unavailable.</p>}
      >
        {primary.length ? (
          evidenceTable(primary)
        ) : (
          <p className="quiet-note flex-center">No resolved factual checks supplied.</p>
        )}
        {remaining.length > 0 && (
          <MoreChecks className="remaining-checks">
            <p>
              Retained checks outside the assessed score. Open a row to inspect
              its evidence and limitations.
            </p>
            {evidenceTable(remaining)}
          </MoreChecks>
        )}
        {!data.criterion?.scoring && <EvidenceRows data={data} onOpen={onOpen} />}
      </EvidenceSection>
      <Coaching data={data} />
    </>
  )
}
