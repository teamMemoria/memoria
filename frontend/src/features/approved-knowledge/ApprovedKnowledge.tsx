import { useWorkspaceSearch } from '../../lib/workspaceSearch'
import { formatDate } from '../../lib/dates'
import { useResource } from '../../lib/useResource'
import { useCallback } from 'react'
import { Link, useParams } from 'react-router'
import { WorkspaceTable } from '../../components/WorkspaceTable'
import { Button, Panel, TextField } from '../../components/controls'
import type { ApprovedKnowledgeApi } from '../../types/knowledge'
import type { Viewer } from '../../types/viewer'
import { filterApprovedKnowledge } from './knowledge'
import { KnowledgeArticleContent } from './KnowledgeArticleContent'
import './approved-knowledge.css'

type Props = { viewer: Viewer; api: ApprovedKnowledgeApi | null }
const columns = [
  { label: 'Title', width: 44 },
  { label: 'Topic', width: 20 },
  { label: 'Type', width: 18 },
  { label: 'Approved', width: 18 },
] as const

export function ApprovedKnowledge({ viewer, api }: Props) {
  const { entryId } = useParams()
  const { filter: setParam, query, search } = useWorkspaceSearch()
  const read = useCallback(async () => {
    if (!entryId) return api!.listForAgent(viewer.id)
    const entry = await api!.getForAgent(viewer.id, entryId)
    return entry?.id === entryId ? [entry] : []
  }, [api, viewer.id, entryId])
  const state = useResource(api ? read : null)
  const available = state.status === 'ready' ? filterApprovedKnowledge(state.data, viewer.id) : []
  const visible = filterApprovedKnowledge(available, viewer.id, query)
  const articleEntry = available.find((item) => item.id === entryId)

  return (
    <div className={`approved-knowledge${articleEntry ? ' approved-knowledge--article' : ''}`}>
      {entryId && (
        <nav className="approved-knowledge-breadcrumb flex-center" aria-label="Breadcrumb">
          <Link className="approved-knowledge-back inline-center" to={`/agent/knowledge${search}`}>
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
      {!api ? (
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
          <Button onClick={state.retry}>Try again</Button>
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
                  hideLabel
                  type="search"
                  label="Search approved knowledge"
                  placeholder="Search approved knowledge"
                  value={query}
                  onChange={(event) => setParam('q', event.target.value)}
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
                        <td className="approved-knowledge-date">{formatDate(item.approvedAt)}</td>
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
                    onClick={() => setParam('q', '')}
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
