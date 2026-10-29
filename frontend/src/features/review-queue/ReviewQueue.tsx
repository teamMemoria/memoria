import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { Icon } from '../../components/Icon'
import {
  Button,
  Panel,
  SelectField,
  StatusLabel,
  TextField,
} from '../../components/controls'
import type { Viewer } from '../../types/viewer'
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

export function ReviewQueue({
  viewer,
  api,
}: {
  viewer: Viewer
  api: TeamReviewApi | null
}) {
  const [params, setParams] = useSearchParams()
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const query = params.get('q') ?? ''
  const status = queueStatusFrom(params.get('status'))
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

  if (viewer.role !== 'manager') {
    return (
      <Panel title="Page unavailable for your role">
        <p>The review queue is available in the Manager workspace.</p>
      </Panel>
    )
  }

  const records = state.status === 'ready' ? state.records : []
  const visible = filterTeamConversations(records, { query, status })
  const flaggedCount = records.filter(
    (record) => record.reviewStatus === 'review-requested',
  ).length

  return (
    <div className="review-queue">
      <h1>Team conversations</h1>
      {state.status === 'ready' && (
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
          placeholder="Search by call, agent, topic or reason"
          value={query}
          onChange={(event) => setParam('q', event.target.value)}
          disabled={state.status !== 'ready'}
        />
        <SelectField
          id="review-queue-status"
          label="Review status"
          value={status}
          onChange={(event) => setParam('status', event.target.value)}
          disabled={state.status !== 'ready'}
        >
          {Object.entries(conversationStatusLabels).map(([value, label]) => (
            <option key={value} value={value}>
              {value === defaultQueueStatus ? `${label} (flagged)` : label}
            </option>
          ))}
        </SelectField>
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
            <p>Try another search or review status.</p>
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
          <div
            className="conversation-table-scroll"
            role="region"
            aria-label="Team conversations table"
            tabIndex={0}
          >
            <table className="conversation-table review-queue-table">
              <caption className="conversation-sr-only">
                Team conversations, flagged feedback newest first.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Call</th>
                  <th scope="col">Agent</th>
                  <th scope="col">Topic</th>
                  <th scope="col">Flag reason</th>
                  <th scope="col">Date</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((conversation) => {
                  const path = findingReviewPath(conversation, search)
                  return (
                    <tr key={conversation.id}>
                      <td>
                        {path ? (
                          <Link
                            to={path}
                            aria-label={`Review ${conversation.id}: ${conversation.flag!.findingTitle}`}
                          >
                            {conversation.id}
                          </Link>
                        ) : (
                          conversation.id
                        )}
                      </td>
                      <td>{conversation.agentName}</td>
                      <td>{conversation.topic}</td>
                      <td>
                        {conversation.flag ? (
                          <span className="review-queue-flag">
                            <span>{conversation.flag.reason}</span>
                            <span className="metadata-line">
                              {conversation.flag.findingTitle}
                            </span>
                          </span>
                        ) : (
                          <span className="review-queue-muted">Not flagged</span>
                        )}
                      </td>
                      <td>
                        <time dateTime={conversation.date}>
                          {formatConversationDate(conversation.date)}
                        </time>
                      </td>
                      <td>
                        {conversation.automatedResult === 'processing' ||
                        !conversation.reviewStatus ? (
                          <StatusLabel>Processing</StatusLabel>
                        ) : (
                          <StatusLabel tone={statusTones[conversation.reviewStatus]}>
                            {reviewStatusLabels[conversation.reviewStatus]}
                          </StatusLabel>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

export function FindingReview({ viewer }: { viewer: Viewer }) {
  const { conversationId = '', findingId = '' } = useParams()
  const [params] = useSearchParams()
  const search = params.size ? `?${params}` : ''

  if (viewer.role !== 'manager') {
    return (
      <Panel title="Page unavailable for your role">
        <p>Finding review is available in the Manager workspace.</p>
      </Panel>
    )
  }

  return (
    <div className="review-queue">
      <Link className="review-queue-back" to={`/manager/conversations${search}`}>
        <Icon name="arrowLeft" />
        Team conversations
      </Link>
      <h1>Review call {conversationId}</h1>
      <p className="metadata-line">
        <span>Finding {findingId}</span>
      </p>
      <p>Manager decisions for this finding are not available yet.</p>
    </div>
  )
}
