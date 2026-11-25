import { useWorkspaceSearch } from '../../lib/workspaceSearch'
import { ConversationFilters, NoMatchingConversations } from '../conversations/ConversationFilters'
import { useResource } from '../../lib/useResource'
import { useCallback, useState } from 'react'
import { ConversationTable } from '../conversations/ConversationTable'
import {
  Button,
  Panel,
  StatusLabel,
} from '../../components/controls'
import type { Viewer } from '../../types/viewer'
import { ConversationScoreBar } from '../conversations/ConversationScoreBar'
import { rankByScore, scoreBandFrom, type ScoreBand } from '../conversations/scoreBands'
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
  type TeamReviewApi,
} from './teamQueue'
import './review-queue.css'

const queueFilters = Object.entries(conversationStatusLabels).map(([value, label]) =>
  [value, value === defaultQueueStatus ? `${label} (flagged)` : label] as const,
)

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
  const { params, filter: setParam, setParams, query, search } = useWorkspaceSearch({ status: defaultQueueStatus })
  const [previewBand, setPreviewBand] = useState<ScoreBand | null>(null)
  const status = simulation ? 'all' : queueStatusFrom(params.get('status'))
  const selectedBand = simulation ? scoreBandFrom(params.get('status')) : null

  const read = useCallback(() => api!.listForManager(viewer.id), [api, viewer.id])
  const state = useResource(api ? read : null)


  function selectScoreBand(value: string) {
    setPreviewBand(null)
    setParam('status', value === 'all' ? '' : value)
  }

  const records = state.status === 'ready' ? state.data : []
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
      <ConversationFilters
        team
        simulation={simulation}
        query={query}
        value={simulation ? selectedBand ?? 'all' : status}
        statusOptions={queueFilters}
        disabled={state.status !== 'ready'}
        onSearch={(value) => setParam('q', value)}
        onSelect={simulation ? selectScoreBand : (value) => setParam('status', value)}
      />
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
            onClick={state.retry}
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
          <NoMatchingConversations scored={simulation} onClear={() => setParams({})} />
        ) : (
          <Panel title="No flagged feedback">
            <p>Nothing needs your review right now.</p>
            <Button variant="secondary" onClick={() => setParam('status', 'all')}>
              Show all conversations
            </Button>
          </Panel>
        )
      ) : (
        <ConversationTable
          rows={visible}
          label="Team conversations table"
          caption={simulation ? 'Team conversations.' : 'Team conversations, flagged feedback newest first.'}
          scored={simulation}
          columns={reviewColumns}
          link={(conversation) => ({
            to: findingReviewPath(conversation, search) ?? `/manager/conversations/${encodeURIComponent(conversation.id)}${search}`,
            'aria-label': simulation ? `Open ABCD ${conversation.sourceId}` : `Review ${conversation.id}: ${conversation.flag?.findingTitle ?? conversation.topic}`,
          })}
          details={(conversation) => (
            <>
              <td>{conversation.agentName}</td>
              <td>{conversation.topic}</td>
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
                <time dateTime={conversation.date ?? undefined}>{formatConversationDate(conversation.date)}</time>
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
        />
      )}
    </div>
  )
}
