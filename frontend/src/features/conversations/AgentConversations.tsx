import { ConversationFilters, NoMatchingConversations } from './ConversationFilters'
import { useConversations } from './controller'
import { useState, type CSSProperties } from 'react'
import { ConversationTable } from './ConversationTable'
import {
  Button,
  Panel,
  StatusLabel,
} from '../../components/controls'
import type { Viewer } from '../../types/viewer'
import {
  automatedResultLabels,
  conversationStatusLabels,
  countConversationStatuses,
  filterConversations,
  reviewStatusLabels,
  type ConversationsApi,
} from './conversations'
import { ConversationScoreBar } from './ConversationScoreBar'
import { rankByScore, scoreBandFrom, type ScoreBand } from './scoreBands'
import './conversations.css'

const filters = Object.entries(conversationStatusLabels)
const reviewColumns = [
  { label: 'Call', width: 10 },
  { label: 'Topic', width: 27 },
  { label: 'Agent', width: 18 },
  { label: 'Automated result', width: 23 },
  { label: 'Review status', width: 22 },
] as const
const resultTones = {
  'needs-review': 'attention',
  'meets-criteria': 'positive',
  'cannot-assess': 'neutral',
  processing: 'neutral',
  unavailable: 'neutral',
} as const

export function AgentConversations({
  viewer,
  api,
  simulation = false,
}: {
  viewer: Viewer
  api: ConversationsApi | null
  simulation?: boolean
}) {
  const { state, previewStatus, setPreviewStatus, query, status, requestedStatus, search, changeFilter, setParams } = useConversations(viewer, api)
  const [previewBand, setPreviewBand] = useState<ScoreBand | null>(null)
  const selectedBand = simulation ? scoreBandFrom(requestedStatus) : null

  function selectScoreBand(value: string) {
    setPreviewBand(null)
    changeFilter('status', value)
  }

  const error = (
    <Panel title="Unable to load conversations">
      <p role="alert">
        {api
          ? 'Your conversations could not be loaded. Please try again.'
          : 'Conversation data is not connected.'}
      </p>
      {api && (
        <Button onClick={state.retry}>
          Try again
        </Button>
      )}
    </Panel>
  )

  const records = state.status === 'ready' ? state.data : []
  const matches = filterConversations(records, {
    query,
    status: simulation ? 'all' : previewStatus ?? status,
  })
  const visible = simulation ? rankByScore(matches, previewBand ?? selectedBand) : matches
  const counts = countConversationStatuses(records)
  const groups = (
    [
      {
        status: 'review-complete',
        count: counts.reviewComplete,
        tone: 'positive',
      },
      {
        status: 'feedback-ready',
        count: counts.feedbackReady,
        tone: 'attention',
      },
      {
        status: 'review-requested',
        count: counts.reviewRequested,
        tone: 'attention',
      },
      {
        status: 'processing',
        count: counts.processing,
        tone: 'neutral',
      },
    ] as const
  ).filter((group) => group.count > 0)
  const summaryColumns = groups
    .map((group, index) => `minmax(0, var(--summary-${index}, ${group.count}fr))`)
    .join(' ')

  return (
    <div className={simulation ? 'agent-conversations agent-conversations--scored' : 'agent-conversations'}>
      <h1>My conversations</h1>
      {simulation && records.length > 0 && (
        <ConversationScoreBar
          records={records}
          selected={selectedBand}
          onPreview={setPreviewBand}
          onSelect={selectScoreBand}
        />
      )}
      {!simulation && state.status === 'ready' && groups.length > 0 && (
        <section
          className="conversation-summary"
          aria-label="Conversation counts"
          style={
            Object.fromEntries(
              groups.map((group, index) => [
                `--summary-expanded-${index}`,
                `${group.count * 1.5}fr`,
              ]),
            ) as CSSProperties
          }
        >
          <div
            className="conversation-count-bar"
            role="group"
            aria-label="Filter conversations by status"
            style={{ gridTemplateColumns: summaryColumns }}
            onMouseLeave={() => setPreviewStatus(null)}
          >
            {groups.map((group) => (
              <button
                key={group.status}
                type="button"
                className={`count-segment count-segment--${group.tone}`}
                aria-label={`${conversationStatusLabels[group.status]}: ${group.count}`}
                aria-pressed={status === group.status}
                onMouseEnter={() => setPreviewStatus(group.status)}
                onClick={() => changeFilter('status', group.status)}
              />
            ))}
          </div>
          <div
            className="conversation-count-labels"
            style={{ gridTemplateColumns: summaryColumns }}
          >
            {groups.map((group) => (
              <StatusLabel key={group.status} tone={group.tone}>
                {conversationStatusLabels[group.status]} {group.count}
              </StatusLabel>
            ))}
          </div>
        </section>
      )}
      <ConversationFilters
        simulation={simulation}
        query={query}
        value={simulation ? selectedBand ?? 'all' : status}
        statusOptions={filters}
        disabled={state.status !== 'ready'}
        onSearch={(value) => changeFilter('q', value, true)}
        onSelect={simulation ? selectScoreBand : (value) => changeFilter('status', value)}
      />
      {state.status === 'loading' && (
        <p role="status">Loading your conversations…</p>
      )}
      {(state.status === 'error' || state.status === 'unavailable') && error}
      {state.status === 'ready' &&
        (records.length === 0 ? (
          <Panel title="No conversations yet">
            <p>{simulation ? 'No conversations are assigned to this profile.' : 'Your completed calls will appear here.'}</p>
          </Panel>
        ) : (
          <>
            <ConversationTable
              rows={visible}
              label="Conversations table"
              caption={simulation ? 'Your conversations.' : 'Your conversations, newest first. Needs review is an automated assessment, not a submitted Manager review request.'}
              scored={simulation}
              columns={reviewColumns}
              link={(conversation) => ({
                className: 'conversation-open',
                to: `/agent/conversations/${encodeURIComponent(conversation.id)}${search}`,
                'aria-label': simulation ? `Open ABCD ${conversation.sourceId}` : `Open conversation ${conversation.id}: ${conversation.topic}`,
              })}
              details={(conversation) => (
                <>
                  <td>{conversation.topic}</td>
                  <td>{conversation.agentName}</td>
                  <td>
                    <StatusLabel tone={resultTones[conversation.automatedResult]}>
                      {automatedResultLabels[conversation.automatedResult]}
                    </StatusLabel>
                  </td>
                  <td className="conversation-review-status">
                    {conversation.reviewStatus ? reviewStatusLabels[conversation.reviewStatus] : 'Not ready'}
                  </td>
                </>
              )}
            />
            {visible.length === 0 && (
              <NoMatchingConversations scored={simulation} onClear={() => {
                setPreviewStatus(null)
                setPreviewBand(null)
                setParams({})
              }} />
            )}
          </>
        ))}
    </div>
  )
}
