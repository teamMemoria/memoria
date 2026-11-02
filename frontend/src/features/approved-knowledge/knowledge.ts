import { canReadKnowledge, type KnowledgeEntry } from '../../types/knowledge'

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeZone: 'UTC',
})

export function formatKnowledgeDate(value: string | null) {
  if (!value) return 'Not supplied'
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`)
  return Number.isNaN(date.valueOf()) ? 'Not supplied' : dateFormatter.format(date)
}

export function filterApprovedKnowledge(
  entries: KnowledgeEntry[],
  agentId: string,
  query = '',
) {
  const search = query.trim().toLowerCase()
  return entries.filter(
    (entry) =>
      canReadKnowledge(entry, agentId) &&
      [entry.id, entry.title, entry.topic, entry.version]
        .join(' ')
        .toLowerCase()
        .includes(search),
  )
}
