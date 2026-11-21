import type { KnowledgeDraft, KnowledgeEntry } from '../../types/knowledge'

export const queueTabs = {
  pending: 'Pending review',
  approved: 'Approved',
  flagged: 'Flagged',
  rejected: 'Rejected',
} as const

export type QueueTab = keyof typeof queueTabs

const tabForStatus = {
  draft: 'pending',
  approved: 'approved',
  disputed: 'flagged',
  stale: 'flagged',
  rejected: 'rejected',
} as const satisfies Record<KnowledgeEntry['status'], QueueTab>

export function queueTabFor(entry: KnowledgeDraft): QueueTab {
  return entry.status === 'draft' && entry.possibleConflicts?.length ? 'flagged' : tabForStatus[entry.status]
}

export function isQueueTab(value: string | null): value is QueueTab {
  return value !== null && value in queueTabs
}

export function countQueueTabs(entries: KnowledgeDraft[]) {
  const counts: Record<QueueTab, number> = {
    pending: 0,
    approved: 0,
    flagged: 0,
    rejected: 0,
  }
  for (const entry of entries) counts[queueTabFor(entry)] += 1
  return counts
}

export function filterQueue(
  entries: KnowledgeDraft[],
  { tab, query }: { tab: QueueTab; query: string },
) {
  const search = query.trim().toLowerCase()
  return entries
    .filter(
      (entry) =>
        queueTabFor(entry) === tab &&
        [entry.id, entry.title, entry.topic]
          .join(' ')
          .toLowerCase()
          .includes(search),
    )
    .sort((first, second) => second.updatedAt.localeCompare(first.updatedAt))
}
