import { useEffect, useState, type CSSProperties } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import {
  Button,
  Panel,
  SelectField,
  StatusLabel,
  TextField,
} from '../../components/controls'
import type { Viewer } from '../../types/viewer'
import {
  automatedResultLabels,
  conversationStatusLabels,
  countConversationStatuses,
  filterConversations,
  formatConversationDate,
  getAgentConversations,
  reviewStatusLabels,
  type Conversation,
  type ConversationsApi,
  type ConversationStatusFilter,
} from './conversations'
import { Icon } from '../../components/Icon'
import './conversations.css'

type LoadState = {
  api: ConversationsApi | null
  agentId: string
} & (
  | { status: 'loading' }
  | { status: 'ready'; records: Conversation[] }
  | { status: 'error' }
)

const filters = Object.entries(conversationStatusLabels)
const resultTones = {
  'needs-review': 'attention',
  'meets-criteria': 'positive',
  'cannot-assess': 'neutral',
  processing: 'neutral',
} as const

export function AgentConversations({
  viewer,
  api,
}: {
  viewer: Viewer
  api: ConversationsApi | null
}) {
  const [loaded, setLoaded] = useState<LoadState>({
    api,
    agentId: viewer.id,
    status: 'loading',
  })
  const [attempt, setAttempt] = useState(0)
  const [previewStatus, setPreviewStatus] =
    useState<ConversationStatusFilter | null>(null)
  const [params, setParams] = useSearchParams()
  const { conversationId } = useParams()
  const query = params.get('q') ?? ''
  const status = (filters.find(
    ([value]) => value === params.get('status'),
  )?.[0] ?? 'all') as ConversationStatusFilter
  const search = params.size ? `?${params}` : ''
  const state = !api
    ? { status: 'error' as const }
    : loaded.api === api && loaded.agentId === viewer.id
      ? loaded
      : { status: 'loading' as const }

  useEffect(() => {
    let active = true
    if (!api) return
    void api.listForAgent(viewer.id).then(
      (records) => {
        if (active)
          setLoaded({
            api,
            agentId: viewer.id,
            status: 'ready',
            records: getAgentConversations(records, viewer.id),
          })
      },
      () => {
        if (active) setLoaded({ api, agentId: viewer.id, status: 'error' })
      },
    )
    return () => {
      active = false
    }
  }, [api, viewer.id, attempt])

  function changeFilter(key: string, value: string, replace = false) {
    if (key === 'status') setPreviewStatus(null)
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        if (!value || (key === 'status' && value === 'all')) next.delete(key)
        else next.set(key, value)
        return next
      },
      { replace },
    )
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

  if (conversationId) {
    const conversation =
      state.status === 'ready'
        ? state.records.find((record) => record.id === conversationId)
        : undefined
    return (
      <div className="conversation-handoff">
        <Link to={`/agent/conversations${search}`}>Back to conversations</Link>
        <h1>
          {conversation
            ? `${conversation.id} · ${conversation.topic}`
            : 'Conversation'}
        </h1>
        {state.status === 'loading' && (
          <p role="status">Loading conversation…</p>
        )}
        {state.status === 'error' && error}
        {state.status === 'ready' &&
          (conversation ? (
            <Panel
              title={
                conversation.automatedResult === 'processing'
                  ? 'Feedback is processing'
                  : 'Call overview is not connected yet'
              }
            >
              <p>
                {conversation.automatedResult === 'processing'
                  ? 'Automatic feedback is not ready for this call.'
                  : 'This conversation opens here. Detailed feedback will be available when the call overview is connected.'}
              </p>
            </Panel>
          ) : (
            <Panel title="Conversation unavailable">
              <p>This conversation is not available in your workspace.</p>
            </Panel>
          ))}
      </div>
    )
  }

  const records = state.status === 'ready' ? state.records : []
  const visible = filterConversations(records, {
    query,
    status: previewStatus ?? status,
  })
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
    <div className="agent-conversations">
      <h1>My conversations</h1>
      {state.status === 'ready' && (
        <>
          {groups.length > 0 && (
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
          <p className="conversation-owner">
            {viewer.displayName} · {records.length}{' '}
            {records.length === 1 ? 'conversation' : 'conversations'}
          </p>
        </>
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
          placeholder="Search calls"
          value={query}
          onChange={(event) => changeFilter('q', event.target.value, true)}
          disabled={state.status !== 'ready'}
        />
        <SelectField
          id="conversation-status"
          label="Review status"
          value={status}
          onChange={(event) => changeFilter('status', event.target.value)}
          disabled={state.status !== 'ready'}
        >
          {filters.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>
      </div>
      {state.status === 'loading' && (
        <p role="status">Loading your conversations…</p>
      )}
      {state.status === 'error' && error}
      {state.status === 'ready' &&
        (records.length === 0 ? (
          <Panel title="No conversations yet">
            <p>Your completed calls will appear here.</p>
          </Panel>
        ) : (
          <>
            <p className="conversation-sr-only" role="status">
              {visible.length}{' '}
              {visible.length === 1 ? 'conversation' : 'conversations'} shown
            </p>
            <div
              className="conversation-table-scroll"
              role="region"
              aria-label="Conversations table"
              tabIndex={0}
            >
              <table className="conversation-table">
                <caption className="conversation-sr-only">
                  Your conversations, newest first. Needs review is an automated
                  assessment, not a submitted Manager review request.
                </caption>
                <colgroup>
                  {[116, 260, 210, 180, 278, 268, 56].map((width, index) => (
                    <col
                      key={index}
                      style={{ width: `${(width / 1368) * 100}%` }}
                    />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">Call</th>
                    <th scope="col">Topic</th>
                    <th scope="col">Agent</th>
                    <th scope="col" aria-sort="descending">
                      Date <span aria-hidden="true">↓</span>
                    </th>
                    <th scope="col">Automated result</th>
                    <th scope="col">Review status</th>
                    <th scope="col">
                      <span className="conversation-sr-only">Open</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((conversation) => (
                    <tr key={conversation.id}>
                      <td>
                        <Link
                          className="conversation-open"
                          to={`/agent/conversations/${encodeURIComponent(conversation.id)}${search}`}
                          aria-label={`Open conversation ${conversation.id}: ${conversation.topic}`}
                        >
                          {conversation.id}
                        </Link>
                      </td>
                      <td>{conversation.topic}</td>
                      <td>{conversation.agentName}</td>
                      <td className="conversation-date">
                        <time dateTime={conversation.date}>
                          {formatConversationDate(conversation.date)}
                        </time>
                      </td>
                      <td>
                        <StatusLabel
                          tone={resultTones[conversation.automatedResult]}
                        >
                          {automatedResultLabels[conversation.automatedResult]}
                        </StatusLabel>
                      </td>
                      <td className="conversation-review-status">
                        {conversation.reviewStatus
                          ? reviewStatusLabels[conversation.reviewStatus]
                          : 'Not ready'}
                      </td>
                      <td>
                        <Icon name="arrowRight" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {visible.length === 0 && (
              <Panel title="No matching conversations">
                <p>Try another search or review status.</p>
                <Button
                  variant="secondary"
                  onClick={() => {
                    setPreviewStatus(null)
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
