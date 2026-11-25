import { canReadKnowledge, type KnowledgeEntry } from '../../types/knowledge'

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
