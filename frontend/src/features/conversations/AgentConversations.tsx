import { useConversations } from './controller'
import { MemoriaSelectField } from '../../components/ui/select'
import { useState, type CSSProperties } from 'react'
import { Link } from 'react-router'
import { WorkspaceTable } from '../../components/WorkspaceTable'
import {
  Button,
  Panel,
  StatusLabel,
  TextField,
} from '../../components/controls'
import { percentage } from '../../types/callReview'
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
import { rankByScore, scoreBandFrom, scoreColumns, scoreOptions, type ScoreBand } from './scoreBands'
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
  const { state, setLoaded, setAttempt, previewStatus, setPreviewStatus, query, status, requestedStatus, search, changeFilter, setParams } = useConversations(viewer, api)
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
        <Button
          onClick={() => {
            setLoaded({ api, agentId: viewer.id, status: 'loading' })
            setAttempt((value) => value + 1)
          }}
        >
          Try again
        </Button>
      )}
    </Panel>
  )

  const records = state.status === 'ready' ? state.records : []
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
      <div
        className="conversation-filters"
        role="search"
        aria-label="Find conversations"
      >
        <TextField
          id="conversation-search"
          label="Search calls"
          type="search"
          placeholder={simulation ? 'Search by call, agent or topic' : 'Search calls'}
          value={query}
          onChange={(event) => changeFilter('q', event.target.value, true)}
          disabled={state.status !== 'ready'}
        />
        {simulation ? (
          <MemoriaSelectField
            id="conversation-score"
            label="Overall score"
            value={selectedBand ?? 'all'}
            onValueChange={selectScoreBand}
            disabled={state.status !== 'ready'}
            options={scoreOptions}
          />
        ) : (
          <MemoriaSelectField
            id="conversation-status"
            label="Review status"
            value={status}
            onValueChange={(value) => changeFilter('status', value)}
            disabled={state.status !== 'ready'}
            options={filters}
          />
        )}
      </div>
      {state.status === 'loading' && (
        <p role="status">Loading your conversations…</p>
      )}
      {state.status === 'error' && error}
      {state.status === 'ready' &&
        (records.length === 0 ? (
          <Panel title="No conversations yet">
            <p>{simulation ? 'No conversations are assigned to this profile.' : 'Your completed calls will appear here.'}</p>
          </Panel>
        ) : (
          <>
            <p className="conversation-sr-only" role="status">
              {visible.length}{' '}
              {visible.length === 1 ? 'conversation' : 'conversations'} shown
            </p>
            <WorkspaceTable
              label="Conversations table"
              caption={simulation ? 'Your conversations.' : 'Your conversations, newest first. Needs review is an automated assessment, not a submitted Manager review request.'}
              columns={simulation ? scoreColumns : reviewColumns}
            >
              {visible.map((conversation) => (
                <tr key={conversation.id}>
                  <td>
                    <Link
                      className="conversation-open"
                      to={`/agent/conversations/${encodeURIComponent(conversation.id)}${search}`}
                      aria-label={simulation ? `Open ABCD ${conversation.sourceId}` : `Open conversation ${conversation.id}: ${conversation.topic}`}
                    >
                      {conversation.sourceId ? `ABCD ${conversation.sourceId}` : conversation.id}
                    </Link>
                  </td>
                  {simulation ? (
                    <>
                      <td>{conversation.agentName}</td>
                      <td>{conversation.topic}</td>
                      <td>{percentage(conversation.simulationScore)}</td>
                    </>
                  ) : (
                    <>
                      <td>{conversation.topic}</td>
                      <td>{conversation.agentName}</td>
                      <td>
                        <StatusLabel tone={resultTones[conversation.automatedResult]}>
                          {automatedResultLabels[conversation.automatedResult]}
                        </StatusLabel>
                      </td>
                      <td className="conversation-review-status">
                        {conversation.reviewStatus
                          ? reviewStatusLabels[conversation.reviewStatus]
                          : 'Not ready'}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </WorkspaceTable>
            {visible.length === 0 && (
              <Panel title="No matching conversations">
                <p>{simulation ? 'Try another search or score range.' : 'Try another search or review status.'}</p>
                <Button
                  variant="secondary"
                  onClick={() => {
                    setPreviewStatus(null)
                    setPreviewBand(null)
                    setParams({})
                  }}
                >
                  Clear filters
                </Button>
              </Panel>
            )}
          </>
        ))}
    </div>
  )
}
