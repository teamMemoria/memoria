import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { CountBar } from '../../components/CountBar'
import { WorkspaceTable } from '../../components/WorkspaceTable'
import { Button, Panel, Tabs, TextField } from '../../components/controls'
import type { KnowledgeDraft, KnowledgeReviewApi } from '../../types/knowledge'
import type { Viewer } from '../../types/viewer'
import { formatKnowledgeDate } from '../approved-knowledge/knowledge'
import { draftLayers, draftPresentation, draftTopic, type DraftLayer } from './draftPresentation'
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

function DraftTable({ entries, caption, search, showSources = true }: {
  entries: KnowledgeDraft[]
  caption: string
  search: string
  showSources?: boolean
}) {
  const columns = [
    { label: 'Title', width: showSources ? 30 : 49 },
    { label: 'Topic', width: 19 },
    ...(showSources ? [{ label: 'Sources', width: 19 }] : []),
    { label: 'Updated', width: 18, sort: 'descending' },
    { label: 'Action', width: 14, hideLabel: true },
  ] as const

  return (
    <WorkspaceTable label={caption} caption={caption} columns={columns}>
      {entries.map((entry) => {
        const path = `/manager/knowledge/${encodeURIComponent(entry.id)}${search}`
        const { title } = draftPresentation(entry.title, entry.layer)
        return (
          <tr key={entry.id}>
            <td>
              <Link to={path}>{title}</Link>
              <span className="knowledge-drafts-sr-only">{entry.id}</span>
            </td>
            <td>{draftTopic(entry.topic)}</td>
            {showSources && (
              <td>
                {entry.sourceConversationIds.length}{' '}
                {entry.sourceConversationIds.length === 1 ? 'source' : 'sources'}
              </td>
            )}
            <td>{formatKnowledgeDate(entry.updatedAt)}</td>
            <td>
              <Link to={path} aria-label={`Review ${title}`}>
                Review
              </Link>
            </td>
          </tr>
        )
      })}
    </WorkspaceTable>
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
  const [generating, setGenerating] = useState(false)
  const [generationMessage, setGenerationMessage] = useState('')
  const [previewTab, setPreviewTab] = useState<QueueTab | null>(null)

  async function generateDrafts() {
    if (!api?.generateDrafts || generating) return
    setGenerating(true)
    setGenerationMessage('')
    try {
      const result = await api.generateDrafts(viewer.id)
      setGenerationMessage(`New drafts: ${result.created}. Skipped: ${result.skipped.length}.`)
      retry()
    } catch {
      setGenerationMessage('Draft generation could not finish.')
    } finally {
      setGenerating(false)
    }
  }
  const requestedTab = params.get('tab')
  const selectedTab: QueueTab = isQueueTab(requestedTab) ? requestedTab : 'pending'
  const tab = previewTab ?? selectedTab
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
  const groups = (Object.keys(draftLayers) as DraftLayer[])
    .map((layer) => ({
      layer,
      entries: visible.filter((entry) => draftPresentation(entry.title, entry.layer).layer === layer),
    }))
    .filter((group) => group.entries.length > 0)
  const showLayers = entries.some((entry) => draftPresentation(entry.title, entry.layer).layer !== 'other')

  const list = visible.length ? (
    showLayers ? (
      <div className="knowledge-draft-groups">
        {groups.map(({ layer, entries: groupEntries }) => (
          <section className="knowledge-draft-group" key={layer} aria-labelledby={`draft-group-${layer}`}>
            <header>
              <h2 id={`draft-group-${layer}`}>{draftLayers[layer]}</h2>
              <span className="metadata-line">
                {groupEntries.length} {groupEntries.length === 1 ? 'entry' : 'entries'}
              </span>
            </header>
            <DraftTable
              entries={groupEntries}
              caption={draftLayers[layer]}
              search={search}
              showSources={layer !== 'layer1'}
            />
          </section>
        ))}
      </div>
    ) : <DraftTable entries={visible} caption={`${queueTabs[tab]} knowledge entries`} search={search} />
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
      {api?.generateDrafts && (
        <Button variant="secondary" onClick={() => void generateDrafts()} disabled={generating}>
          {generating ? 'Generating…' : 'Generate pilot drafts'}
        </Button>
      )}
      {generationMessage && <p role="status">{generationMessage}</p>}
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
          <CountBar
            label="Knowledge draft counts"
            segments={[
              { value: 'approved', label: queueTabs.approved, count: counts.approved, tone: 'positive' },
              { value: 'pending', label: queueTabs.pending, count: counts.pending, tone: 'attention' },
              { value: 'flagged', label: queueTabs.flagged, count: counts.flagged, tone: 'neutral' },
            ]}
            selected={selectedTab}
            onPreview={setPreviewTab}
            onSelect={(value) => {
              setPreviewTab(null)
              setParam('tab', value)
            }}
          />
          <Tabs
            label="Review status"
            value={tab}
            onChange={(value) => {
              setPreviewTab(null)
              setParam('tab', value)
            }}
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
