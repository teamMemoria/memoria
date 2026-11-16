import { featuredChecks, type AssessmentData } from '../assessment-shared/assessment'

export function presentAnswer(data: AssessmentData, selectedId: string | null) {
  const ordered = featuredChecks(data.checks)
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
  return { ordered, featured, primary, remaining, claim, reference, sources }
}
