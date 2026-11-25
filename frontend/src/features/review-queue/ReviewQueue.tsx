import { MemoriaSelectField } from '../../components/ui/select'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { WorkspaceTable } from '../../components/WorkspaceTable'
import {
  Button,
  Panel,
  StatusLabel,
  TextField,
} from '../../components/controls'
import { percentage } from '../../types/callReview'
import type { Viewer } from '../../types/viewer'
import { ConversationScoreBar } from '../conversations/ConversationScoreBar'
import { rankByScore, scoreBandFrom, scoreColumns, scoreOptions, type ScoreBand } from '../conversations/scoreBands'
import {
  conversationStatusLabels,
  formatConversationDate,
  reviewStatusLabels,
  type ReviewStatus,
} from '../conversations/conversations'
import '../conversations/conversations.css'
import {
  defaultQueueStatus,
  filterTeamConversations,
  findingReviewPath,
  queueStatusFrom,
  type TeamConversation,
  type TeamReviewApi,
} from './teamQueue'
import './review-queue.css'

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; records: TeamConversation[] }

const statusTones = {
  'review-requested': 'attention',
  'review-complete': 'positive',
  'feedback-ready': 'neutral',
} as const satisfies Record<ReviewStatus, 'neutral' | 'positive' | 'attention'>

const reviewColumns = [
  { label: 'Call', width: 9 },
  { label: 'Agent', width: 13 },
  { label: 'Topic', width: 15 },
  { label: 'Flag reason', width: 33 },
  { label: 'Date', width: 12 },
  { label: 'Status', width: 18 },
] as const

export function ReviewQueue({
  viewer,
  api,
  simulation = false,
}: {
  viewer: Viewer
  api: TeamReviewApi | null
  simulation?: boolean
}) {
  const [params, setParams] = useSearchParams()
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [previewBand, setPreviewBand] = useState<ScoreBand | null>(null)
  const query = params.get('q') ?? ''
  const status = simulation ? 'all' : queueStatusFrom(params.get('status'))
  const selectedBand = simulation ? scoreBandFrom(params.get('status')) : null
  const search = params.size ? `?${params}` : ''

  // Reloads on every visit so the queue reflects decisions made elsewhere.
  useEffect(() => {
    let active = true
    if (!api || viewer.role !== 'manager') return
    void api.listForManager(viewer.id).then(
      (records) => {
        if (active) setState({ status: 'ready', records })
      },
      () => {
        if (active) setState({ status: 'error' })
      },
    )
    return () => {
      active = false
    }
  }, [api, viewer.id, viewer.role, attempt])

  function setParam(key: 'q' | 'status', value: string) {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        if (!value || (key === 'status' && value === defaultQueueStatus)) next.delete(key)
        else next.set(key, value)
        return next
      },
      { replace: true },
    )
  }

  function selectScoreBand(value: string) {
    setPreviewBand(null)
    setParam('status', value === 'all' ? '' : value)
  }

  if (viewer.role !== 'manager') {
    return (
      <Panel title="Page unavailable for your role">
        <p>The review queue is available in the Manager workspace.</p>
      </Panel>
    )
  }

  const records = state.status === 'ready' ? state.records : []
  const matches = filterTeamConversations(records, { query, status })
  const visible = simulation ? rankByScore(matches, previewBand ?? selectedBand) : matches
  const flaggedCount = records.filter(
    (record) => record.reviewStatus === 'review-requested',
  ).length

  return (
    <div className={`review-queue${simulation ? ' review-queue--simulation' : ''}`}>
      <h1>Team conversations</h1>
      {simulation && records.length > 0 && (
        <ConversationScoreBar
          records={records}
          selected={selectedBand}
          onPreview={setPreviewBand}
          onSelect={selectScoreBand}
        />
      )}
      {!simulation && state.status === 'ready' && (
        <p className="review-queue-summary">
          <StatusLabel tone={flaggedCount ? 'attention' : 'positive'}>
            {flaggedCount} flagged for review
          </StatusLabel>
        </p>
      )}
      <div
        className="conversation-filters"
        role="search"
        aria-label="Find team conversations"
      >
        <TextField
          id="review-queue-search"
          label="Search team calls"
          type="search"
          placeholder={simulation ? 'Search by call, agent or topic' : 'Search by call, agent, topic or reason'}
          value={query}
          onChange={(event) => setParam('q', event.target.value)}
          disabled={state.status !== 'ready'}
        />
        {simulation ? (
          <MemoriaSelectField
            id="review-queue-score"
            label="Overall score"
            value={selectedBand ?? 'all'}
            onValueChange={selectScoreBand}
            disabled={state.status !== 'ready'}
            options={scoreOptions}
          />
        ) : <MemoriaSelectField
          id="review-queue-status"
          label="Review status"
          value={status}
          onValueChange={(value) => setParam('status', value)}
          disabled={state.status !== 'ready'}
          options={Object.entries(conversationStatusLabels).map(([value, label]) => [value, value === defaultQueueStatus ? `${label} (flagged)` : label] as const)}
        />}
      </div>
      {!api ? (
        <Panel title="Team review unavailable">
          <p>Team review data is not connected.</p>
        </Panel>
      ) : state.status === 'loading' ? (
        <p role="status">Loading team conversations…</p>
      ) : state.status === 'error' ? (
        <Panel title="Unable to load team conversations">
          <p role="alert">Team conversations could not be loaded. Please try again.</p>
          <Button
            onClick={() => {
              setState({ status: 'loading' })
              setAttempt((value) => value + 1)
            }}
          >
            Try again
          </Button>
        </Panel>
      ) : records.length === 0 ? (
        <Panel title="No team conversations yet">
          <p>Your team’s completed calls will appear here.</p>
        </Panel>
      ) : visible.length === 0 ? (
        query.trim() || status !== defaultQueueStatus ? (
          <Panel title="No matching conversations">
            <p>{simulation ? 'Try another search or score range.' : 'Try another search or review status.'}</p>
            <Button variant="secondary" onClick={() => setParams({})}>
              Clear filters
            </Button>
          </Panel>
        ) : (
          <Panel title="No flagged feedback">
            <p>Nothing needs your review right now.</p>
            <Button variant="secondary" onClick={() => setParam('status', 'all')}>
              Show all conversations
            </Button>
          </Panel>
        )
      ) : (
        <>
          <p className="conversation-sr-only" role="status">
            {visible.length} {visible.length === 1 ? 'conversation' : 'conversations'} shown
          </p>
          <WorkspaceTable
            label="Team conversations table"
            caption={simulation ? 'Team conversations.' : 'Team conversations, flagged feedback newest first.'}
            columns={simulation ? scoreColumns : reviewColumns}
          >
            {visible.map((conversation) => {
              const path = findingReviewPath(conversation, search) ?? `/manager/conversations/${encodeURIComponent(conversation.id)}${search}`
              return (
                <tr key={conversation.id}>
                  <td>
                    <Link
                      to={path}
                      aria-label={simulation ? `Open ABCD ${conversation.sourceId}` : `Review ${conversation.id}: ${conversation.flag?.findingTitle ?? conversation.topic}`}
                    >
                      {conversation.sourceId ? `ABCD ${conversation.sourceId}` : conversation.id}
                    </Link>
                  </td>
                  <td>{conversation.agentName}</td>
                  <td>{conversation.topic}</td>
                  {simulation ? (
                    <td>{percentage(conversation.simulationScore)}</td>
                  ) : (
                    <>
                      <td>
                        {conversation.flag ? (
                          <span className="review-queue-flag">
                            <span>{conversation.flag.reason}</span>
                            <span className="metadata-line">{conversation.flag.findingTitle}</span>
                          </span>
                        ) : (
                          <span className="review-queue-muted">Not flagged</span>
                        )}
                      </td>
                      <td>
                        <time dateTime={conversation.date ?? undefined}>
                          {formatConversationDate(conversation.date)}
                        </time>
                      </td>
                      <td>
                        {conversation.automatedResult === 'processing' || !conversation.reviewStatus ? (
                          <StatusLabel>{conversation.automatedResult === 'unavailable' ? 'Assessment unavailable' : 'Processing'}</StatusLabel>
                        ) : (
                          <StatusLabel tone={statusTones[conversation.reviewStatus]}>
                            {reviewStatusLabels[conversation.reviewStatus]}
                          </StatusLabel>
                        )}
                      </td>
                    </>
                  )}
                </tr>
              )
            })}
          </WorkspaceTable>
        </>
      )}
    </div>
  )
}
