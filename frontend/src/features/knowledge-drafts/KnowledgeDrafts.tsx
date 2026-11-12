import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Icon } from '../../components/Icon'
import { Button, Panel, Tabs, TextField } from '../../components/controls'
import type { KnowledgeDraft, KnowledgeReviewApi } from '../../types/knowledge'
import type { Viewer } from '../../types/viewer'
import { formatKnowledgeDate } from '../approved-knowledge/knowledge'
import {
  countQueueTabs,
  filterQueue,
  isQueueTab,
  queueTabs,
  type QueueTab,
} from './draftsQueue'
import './knowledge-drafts.css'

type Props = { viewer: Viewer; api: KnowledgeReviewApi | null }
type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; entries: KnowledgeDraft[] }

function KnowledgeCounts({ counts }: { counts: Record<QueueTab, number> }) {
  const maximum = Math.max(
    10,
    Math.ceil(Math.max(...Object.values(counts)) / 10) * 10,
  )
  const statuses = ['pending', 'approved', 'flagged'] as const

  return (
    <figure className="knowledge-counts" aria-label="Knowledge draft counts">
      <figcaption className="knowledge-drafts-sr-only">
        {statuses
          .map((status) => `${queueTabs[status]}: ${counts[status]}`)
          .join('. ')}
      </figcaption>
      <div className="knowledge-counts-bars" aria-hidden="true">
        {statuses.map((status) => (
          <div className="knowledge-counts-row" key={status}>
            <span>{queueTabs[status]}</span>
            <div className="knowledge-counts-track">
              <span
                className={`knowledge-counts-bar knowledge-counts-bar--${status}`}
                style={{ width: `${(counts[status] / maximum) * 100}%` }}
              />
              <strong>{counts[status]}</strong>
            </div>
          </div>
        ))}
      </div>
      <div className="knowledge-counts-axis" aria-hidden="true">
        {Array.from({ length: 11 }, (_, index) => (
          <span key={index}>{(index * maximum) / 10}</span>
        ))}
      </div>
    </figure>
  )
}

function useKnowledgeQueue(api: KnowledgeReviewApi | null, viewer: Viewer) {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  // Reloads on every visit so counts reflect decisions made elsewhere.
  useEffect(() => {
    let active = true
    if (!api || viewer.role !== 'manager') return
    void api.listForManager(viewer.id).then(
      (entries) => {
        if (active) setState({ status: 'ready', entries })
      },
      () => {
        if (active) setState({ status: 'error' })
      },
    )
    return () => {
      active = false
    }
  }, [api, viewer.id, viewer.role, attempt])

  function retry() {
    setState({ status: 'loading' })
    setAttempt((value) => value + 1)
  }

  return { state, retry }
}

export function KnowledgeDrafts({ viewer, api }: Props) {
  const [params, setParams] = useSearchParams()
  const { state, retry } = useKnowledgeQueue(api, viewer)
  const requestedTab = params.get('tab')
  const tab: QueueTab = isQueueTab(requestedTab) ? requestedTab : 'pending'
  const query = params.get('q') ?? ''
  const search = params.size ? `?${params}` : ''

  function setParam(key: 'tab' | 'q', value: string) {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        if (value && !(key === 'tab' && value === 'pending'))
          next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true },
    )
  }

  if (viewer.role !== 'manager') {
    return (
      <Panel title="Page unavailable for your role">
        <p>Knowledge drafts are available in the Manager workspace.</p>
      </Panel>
    )
  }

  const entries = state.status === 'ready' ? state.entries : []
  const counts = countQueueTabs(entries)
  const visible = filterQueue(entries, { tab, query })

  const list = visible.length ? (
    <table className="knowledge-drafts-table">
      <caption className="knowledge-drafts-sr-only">
        {queueTabs[tab]} knowledge entries
      </caption>
      <colgroup>
        {[30, 19, 19, 18, 14].map((width, index) => (
          <col key={index} style={{ width: `${width}%` }} />
        ))}
      </colgroup>
      <thead>
        <tr>
          <th scope="col">Title</th>
          <th scope="col">Topic</th>
          <th scope="col">Sources</th>
          <th scope="col">Updated</th>
          <th scope="col">
            <span className="knowledge-drafts-sr-only">Action</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {visible.map((entry) => (
          <tr key={entry.id}>
            <td>
              <span className="knowledge-drafts-title">
                <Link
                  to={`/manager/knowledge/${encodeURIComponent(entry.id)}${search}`}
                >
                  {entry.title}
                </Link>
                <span className="knowledge-drafts-sr-only">
                  <span>{entry.id}</span>
                </span>
              </span>
            </td>
            <td>{entry.topic}</td>
            <td>
              {entry.sourceConversationIds.length}{' '}
              {entry.sourceConversationIds.length === 1 ? 'source' : 'sources'}
            </td>
            <td>{formatKnowledgeDate(entry.updatedAt)}</td>
            <td>
              <Link
                className="knowledge-drafts-action"
                to={`/manager/knowledge/${encodeURIComponent(entry.id)}${search}`}
                aria-label={`Review ${entry.title}`}
              >
                Review <Icon name="arrowRight" />
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  ) : query.trim() ? (
    <Panel title="No matching entries">
      <p>Try another search in {queueTabs[tab].toLowerCase()} entries.</p>
      <Button variant="secondary" onClick={() => setParam('q', '')}>
        Clear search
      </Button>
    </Panel>
  ) : (
    <Panel title={`No ${queueTabs[tab].toLowerCase()} entries`}>
      <p>Entries appear here when their review status changes.</p>
    </Panel>
  )

  return (
    <div className="knowledge-drafts">
      <h1>Knowledge drafts</h1>
      {!api ? (
        <Panel title="Knowledge review unavailable">
          <p>Knowledge review is not connected.</p>
        </Panel>
      ) : state.status === 'loading' ? (
        <p role="status">Loading knowledge drafts…</p>
      ) : state.status === 'error' ? (
        <Panel title="Unable to load knowledge drafts">
          <p role="alert">
            Knowledge drafts could not be loaded. Please try again.
          </p>
          <Button onClick={retry}>Try again</Button>
        </Panel>
      ) : (
        <>
          <KnowledgeCounts counts={counts} />
          <Tabs
            label="Review status"
            value={tab}
            onChange={(value) => setParam('tab', value)}
            items={(Object.keys(queueTabs) as QueueTab[]).map((value) => ({
              value,
              label: `${queueTabs[value]} (${counts[value]})`,
              content:
                value === tab ? (
                  <div className="knowledge-drafts-results">
                    <div role="search" aria-label="Find knowledge entries">
                      <TextField
                        id="knowledge-drafts-search"
                        type="search"
                        label="Search knowledge entries"
                        placeholder="Search drafts"
                        value={query}
                        onChange={(event) => setParam('q', event.target.value)}
                      />
                    </div>
                    {list}
                  </div>
                ) : null,
            }))}
          />
        </>
      )}
    </div>
  )
}
