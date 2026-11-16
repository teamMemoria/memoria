import { Card } from '../../components/ui/card'
import { percentage } from '../../types/callReview'
import { CheckEvidence } from './AssessmentElements'
import { checkLabels, type ScreenProps } from './assessment'

export function ScoringDetails({ data, onOpen }: ScreenProps) {
  const scoring = data.criterion?.scoring
  if (!scoring) return null
  const version = data.call.assessmentVersion
  return (
    <Card className="dashboard-card evidence-section scoring-details">
      <details>
        <summary>
          <h2>Calculation and evidence</h2>
        </summary>
        {version && (
          <p>
            Prepared local-demo assessment · {version.asOf} · {version.rules}.
            Approval and evidence were checked for that assessment date; this is
            not a fresh policy verification.
          </p>
        )}
        {!scoring.processingError && (
          <p>
            {scoring.assessable > 0
              ? `${scoring.earned} earned ÷ ${scoring.assessable} assessed points × 100 = ${percentage(scoring.score)}.`
              : 'No supported points to score.'}{' '}
            Evidence coverage: {percentage(scoring.coverage, 'Unknown')}.
            Unresolved checks are excluded from the percentage, not treated as
            passes or failures.
          </p>
        )}
        {scoring.checks.map((check) => (
          <section className="calculation-check" key={check.id}>
            <h3>
              {check.critical && 'Critical · '}
              {check.requirement} · {checkLabels[check.outcome]} ·{' '}
              {check.earned == null
                ? 'Unscored'
                : `${check.earned}/${check.maximum}`}
            </h3>
            <CheckEvidence check={check} onOpen={onOpen} />
          </section>
        ))}
        <details>
          <summary>Limitations and interpretation boundaries</summary>
          {[
            ...new Set([
              ...scoring.limitations,
              ...scoring.interpretationLimits,
            ]),
          ].map((text) => (
            <p key={text}>{text}</p>
          ))}
        </details>
      </details>
    </Card>
  )
}
