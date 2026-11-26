import type { ScoringCheck } from '../../types/callReview'
import { featuredChecks, type AssessmentData } from '../assessment-shared/assessment'

const sentenceSegmenter = new Intl.Segmenter('en', { granularity: 'sentence' })
const recoveryEmailRequirement = 'Ensure claims that the recovery email was sent match the recorded outcome'

export function answerEvidencePreview(check: ScoringCheck) {
  const quote = check.citations.find((citation) => citation.kind === 'conversation')?.quote.trim()
  const evidence = quote || check.explanation.trim()
  return sentenceSegmenter.segment(evidence).containing(0)?.segment.trim() ?? evidence
}

export function presentAnswer(data: AssessmentData, selectedId: string | null) {
  const ordered = featuredChecks(data.checks)
  const featured =
    ordered.find((check) => check.id === selectedId) ?? ordered[0]
  const primary = ordered.filter(
    (check) =>
      check.critical ||
      ['supported', 'partial', 'breach'].includes(check.outcome),
  )
  const remaining = ordered.filter((check) => !primary.includes(check))
  const citations = featured?.citations ?? []
  const conversation = citations.filter((citation) => citation.kind === 'conversation')
  const statements = conversation.filter((citation) => citation.event_kind === 'message')
  const references = citations.filter((citation) => citation.kind === 'reference')
  const actions = conversation.filter((citation) => citation.event_kind === 'action')
  const latestAction = actions.toSorted((a, b) => b.turn_id - a.turn_id)[0]
  const plannedRecoverySend = featured?.requirement === recoveryEmailRequirement &&
    actions.length > 0 && actions.every((citation) => /^a link will be sent\.?$/i.test(citation.quote.trim()))
  const summary = plannedRecoverySend
    ? 'The cited system record describes a planned send. Completion is unverified.'
    : featured?.explanation
  const sources = featured
    ? [
        {
          title: 'Conversation evidence',
          count: statements.length,
          detail: statements[0]?.quote ?? 'Statement evidence unavailable',
        },
        {
          title: 'Reference',
          count: references.length,
          detail: references[0]?.quote ?? 'No eligible reference supplied',
        },
        {
          title: 'System record',
          count: actions.length,
          detail: latestAction?.quote ?? 'Independent action evidence unavailable',
        },
      ]
    : []
  return { featured, primary, remaining, sources, summary }
}
