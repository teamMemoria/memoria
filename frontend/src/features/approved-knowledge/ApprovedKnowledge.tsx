import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { WorkspaceTable } from '../../components/WorkspaceTable'
import { Button, Panel, TextField } from '../../components/controls'
import {
  canReadKnowledge,
  type ApprovedKnowledgeApi,
  type KnowledgeEntry,
} from '../../types/knowledge'
import type { Viewer } from '../../types/viewer'
import { filterApprovedKnowledge, formatKnowledgeDate } from './knowledge'
import { KnowledgeArticleContent } from './KnowledgeArticleContent'
import './approved-knowledge.css'

type Props = { viewer: Viewer; api: ApprovedKnowledgeApi | null }
const columns = [
  { label: 'Title', width: 44 },
  { label: 'Topic', width: 20 },
  { label: 'Type', width: 18 },
  { label: 'Approved', width: 18 },
] as const

type LoadState = {
  api: ApprovedKnowledgeApi | null
  agentId: string
  entryId: string | undefined
} & (
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; entries: KnowledgeEntry[] }
)

export function ApprovedKnowledge({ viewer, api }: Props) {
  const { entryId } = useParams()
  const [params, setParams] = useSearchParams()
  const [attempt, setAttempt] = useState(0)
  const [loaded, setLoaded] = useState<LoadState>({
    api,
    agentId: viewer.id,
    entryId,
    status: 'loading',
  })
  const identity = { api, agentId: viewer.id, entryId }
  const isCurrentRequest =
    loaded.api === api &&
    loaded.agentId === viewer.id &&
    loaded.entryId === entryId

  if (!isCurrentRequest) {
    setLoaded({ ...identity, status: 'loading' })
  }

  const state = isCurrentRequest ? loaded : { status: 'loading' as const }
  const query = params.get('q') ?? ''
  const search = params.size ? `?${params}` : ''

  useEffect(() => {
    let active = true
    if (!api || viewer.role !== 'agent') return

    void (async () => {
      try {
        const entry = entryId
          ? await api.getForAgent(viewer.id, entryId)
          : null
        const entries = entryId
          ? entry && entry.id === entryId
            ? [entry]
            : []
          : await api.listForAgent(viewer.id)
        if (active) {
          setLoaded({
            api,
            agentId: viewer.id,
            entryId,
            status: 'ready',
            entries: filterApprovedKnowledge(entries, viewer.id),
          })
        }
      } catch {
        if (active) {
          setLoaded({ api, agentId: viewer.id, entryId, status: 'error' })
        }
      }
    })()

    return () => {
      active = false
    }
  }, [api, viewer.id, viewer.role, entryId, attempt])

  function retry() {
    setLoaded({ ...identity, status: 'loading' })
    setAttempt((value) => value + 1)
  }

  const available =
    state.status === 'ready'
      ? filterApprovedKnowledge(state.entries, viewer.id)
      : []
  const visible = filterApprovedKnowledge(available, viewer.id, query)
  const entry = available.find((item) => item.id === entryId)
  const articleEntry =
    viewer.role === 'agent' && api && entry && canReadKnowledge(entry, viewer.id)
      ? entry
      : undefined

  return (
    <div className={`approved-knowledge${articleEntry ? ' approved-knowledge--article' : ''}`}>
      {entryId && (
        <nav className="approved-knowledge-breadcrumb" aria-label="Breadcrumb">
          <Link className="approved-knowledge-back" to={`/agent/knowledge${search}`}>
            Approved knowledge
          </Link>
          {articleEntry && (
            <>
              <span aria-hidden="true">/</span>
              <span aria-current="page">{articleEntry.title}</span>
            </>
          )}
        </nav>
      )}
      {!articleEntry && <h1>Approved knowledge</h1>}
      {viewer.role !== 'agent' ? (
        <Panel title="Page unavailable for your role">
          <p>This is the Agent knowledge workspace.</p>
          <Link to="/manager/conversations">Back to your conversations</Link>
        </Panel>
      ) : !api ? (
        <Panel title="Knowledge unavailable">
          <p>Approved knowledge is not connected.</p>
        </Panel>
      ) : state.status === 'loading' ? (
        <p role="status">Loading approved knowledge…</p>
      ) : state.status === 'error' ? (
        <Panel title="Unable to load approved knowledge">
          <p role="alert">
            Approved guidance could not be loaded. Please try again.
          </p>
          <Button onClick={retry}>Try again</Button>
        </Panel>
      ) : entryId ? (
        articleEntry ? (
          <KnowledgeArticleContent entry={articleEntry} />
        ) : (
          <Panel title="Entry unavailable">
            <p>This entry is not available as approved guidance in your workspace.</p>
          </Panel>
        )
      ) : (
        <>
          {available.length > 0 ? (
            <>
              <div
                className="approved-knowledge-search"
                role="search"
                aria-label="Find approved guidance"
              >
                <TextField
                  id="approved-knowledge-search"
                  type="search"
                  label="Search approved knowledge"
                  placeholder="Search approved knowledge"
                  value={query}
                  onChange={(event) => {
                    const next = new URLSearchParams(params)
                    if (event.target.value) next.set('q', event.target.value)
                    else next.delete('q')
                    setParams(next, { replace: true })
                  }}
                />
              </div>
              {visible.length > 0 ? (
                <WorkspaceTable
                  label="Approved entries"
                  caption="Approved entries"
                  columns={columns}
                >
                  {visible.map((item) => {
                    const version = item.version.replace(/^v(?=\d)/i, '')
                    return (
                      <tr key={item.id}>
                        <td>
                          <Link
                            to={`/agent/knowledge/${encodeURIComponent(item.id)}${search}`}
                            aria-label={`Open ${item.title}, ${item.id} version ${version}`}
                          >
                            {item.title}
                          </Link>
                          <span className="metadata-line">
                            <span>{item.id}</span>
                            <span>Version {version}</span>
                          </span>
                        </td>
                        <td>{item.topic}</td>
                        <td>{item.kind === 'procedure' ? 'Procedure' : 'Knowledge'}</td>
                        <td className="approved-knowledge-date">{formatKnowledgeDate(item.approvedAt)}</td>
                      </tr>
                    )
                  })}
                </WorkspaceTable>
              ) : (
                <Panel
                  title="No matching guidance"
                  className="approved-knowledge-empty"
                >
                  <p>Try another search to find approved guidance.</p>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      const next = new URLSearchParams(params)
                      next.delete('q')
                      setParams(next, { replace: true })
                    }}
                  >
                    Clear search
                  </Button>
                </Panel>
              )}
            </>
          ) : (
            <Panel title="No approved guidance yet">
              <p>
                Approved procedures and knowledge entries will appear here when available.
              </p>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}

export { ApprovedKnowledge as KnowledgeArticle }
