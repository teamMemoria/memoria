import { Link, useParams, useSearchParams } from 'react-router'
import { Icon } from '../../components/Icon'
import { Button, Panel, StatusLabel } from '../../components/controls'
import { useCallReview } from '../../lib/useCallReview'
import { auditResults as results } from '../../types/callReview'
import type {
  AuditCriterion,
  CallApi,
  CallReview,
  ManagerCallApi,
} from '../../types/callReview'
import type { Viewer } from '../../types/viewer'
import './call-overview.css'

const decisionLabels = {
  confirmed: 'Confirmed',
  corrected: 'Corrected',
  dismissed: 'Dismissed',
  'cannot-assess': 'Cannot assess',
} as const

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeZone: 'UTC',
})

function formatDate(value: string | null) {
  if (!value) return 'Date not recorded'
  return dateFormatter.format(new Date(`${value.slice(0, 10)}T00:00:00Z`))
}

function formatDuration(value: string | null) {
  if (!value) return 'Duration not recorded'
  const match = /^(\d+):([0-5]\d)$/.exec(value)
  return match ? `${Number(match[1])} min ${Number(match[2])} sec` : value
}

export function CallOverview({
  viewer,
  api,
  managerApi = null,
}: {
  viewer: Viewer
  api: CallApi | null
  managerApi?: ManagerCallApi | null
}) {
  const { conversationId = '' } = useParams()
  const [params] = useSearchParams()
  const state = useCallReview(
    viewer.role === 'agent' ? api : null,
    viewer.id,
    conversationId,
    viewer.role === 'manager' ? managerApi : null,
  )
  const backParams = new URLSearchParams()
  for (const key of ['q', 'status']) {
    if (params.has(key)) backParams.set(key, params.get(key)!)
  }
  const search = backParams.size ? `?${backParams}` : ''

  return (
    <div className="call-overview">
      <Link
        className="call-overview-back"
        to={`/${viewer.role}/conversations${search}`}
      >
        <Icon name="arrowLeft" /> Conversations
      </Link>
      {state.status === 'ready' ? (
        <CallContent
          key={state.call.id}
          call={state.call}
          search={search}
          role={viewer.role}
        />
      ) : (
        <div className="call-overview-state">
          <h1>Call overview</h1>
          {state.status === 'loading' && (
            <p role="status">Loading conversation…</p>
          )}
          {state.status === 'error' && (
            <Panel title="Unable to load conversation">
              <p role="alert">
                Your conversation could not be loaded. Please try again.
              </p>
              <Button onClick={state.retry}>Try again</Button>
            </Panel>
          )}
          {state.status === 'unavailable' && (
            <Panel title="Conversation unavailable">
              <p>
                {api
                  ? 'This conversation is not available in your workspace.'
                  : 'Conversation data is not connected.'}
              </p>
            </Panel>
          )}
        </div>
      )}
    </div>
  )
}

function CallContent({
  call,
  search,
  role,
}: {
  call: CallReview
  search: string
  role: Viewer['role']
}) {
  const base = `/${role}/conversations/${encodeURIComponent(call.id)}`
  const transcriptParams = new URLSearchParams(search)
  transcriptParams.set('transcript', 'full')
  const transcript =
    role === 'agent'
      ? `${base}/transcript${search}`
      : `${base}/assessments/procedure?${transcriptParams}`

  function evidenceLink(criterion: AuditCriterion) {
    return `${base}/assessments/${criterion.id}${search}`
  }

  return (
    <>
      <h1>{call.topic}</h1>
      <ul className="call-overview-metadata" aria-label="Call details">
        <li>Call {call.id}</li>
        <li>{call.agentName}</li>
        <li>
          <time dateTime={call.date ?? undefined}>{formatDate(call.date)}</time>
        </li>
        <li>
          <span className="call-overview-sr-only">Duration </span>
          {formatDuration(call.duration)}
        </li>
      </ul>
      <p className="call-overview-summary">{call.summary}</p>
      {call.status === 'processing' ? (
        <Panel title="Feedback is processing">
          <p role="status">Automatic feedback is not ready for this call.</p>
          <Link to={transcript}>Transcript</Link>
        </Panel>
      ) : (
        <>
          <section className="call-audit" aria-label="Automatic feedback">
            <div className="call-audit-diagram">
              <div className="call-audit-root">
                <span className="call-audit-phone">
                  <Icon name="phone" size={24} />
                </span>
                <span>{call.id}</span>
              </div>
              <div className="call-criteria">
                {call.criteria.map((criterion) => {
                  const result = results[criterion.result]
                  const cardContent = (
                    <>
                      <span className="call-criterion-marker">
                        <Icon
                          name={
                            criterion.id === 'procedure' ? 'document' : 'people'
                          }
                          size={24}
                        />
                      </span>
                      <span className="call-criterion-title">
                        {criterion.title}
                      </span>
                      <span className="call-criterion-result">
                        {result.label}
                      </span>
                      {criterion.id === 'communication-style' && (
                        <span className="call-criterion-qualification">
                          Text only
                        </span>
                      )}
                    </>
                  )
                  const connectionTone =
                    criterion.result === 'needs-review'
                      ? 'attention'
                      : criterion.result === 'meets-criteria' &&
                          criterion.id === 'communication-style'
                        ? 'positive'
                        : 'neutral'
                  return (
                    <div
                      className={`call-criterion-column call-criterion-column--${connectionTone}`}
                      key={criterion.id}
                    >
                      <Link
                        className={`call-criterion call-criterion--${result.tone}`}
                        to={evidenceLink(criterion)}
                        aria-label={`${criterion.title}: ${result.label}`}
                      >
                        {cardContent}
                      </Link>
                    </div>
                  )
                })}
              </div>
            </div>
          </section>
          {call.findings.length > 0 ? (
            <section
              className="call-finding-strip"
              aria-label="Automated findings"
            >
              <span className="call-finding-marker">
                <Icon name="info" size={24} />
              </span>
              <div className="call-finding-copy">
                <h2>
                  {call.findings.length} automated{' '}
                  {call.findings.length === 1 ? 'finding' : 'findings'}
                </h2>
                {call.findings.map((finding) => (
                  <p key={finding.id}>{finding.title}</p>
                ))}
              </div>
              <div className="call-finding-actions">
                <Link
                  className="button button--primary"
                  to={`${base}/findings/${encodeURIComponent(call.findings[0].id)}${search}`}
                >
                  View feedback
                </Link>
                <Link className="button button--secondary" to={transcript}>
                  Transcript
                </Link>
              </div>
            </section>
          ) : (
            <Link className="call-transcript-link" to={transcript}>
              Transcript
            </Link>
          )}
          {call.decision && (
            <Panel className="call-manager-decision" title="Manager decision">
              <StatusLabel
                tone={
                  call.decision.outcome === 'cannot-assess'
                    ? 'neutral'
                    : 'positive'
                }
              >
                {decisionLabels[call.decision.outcome]}
              </StatusLabel>
              <p>{call.decision.reason}</p>
              <h3>Feedback</h3>
              <p>{call.decision.feedback}</p>
              <p className="call-overview-decision-meta metadata-line">
                <span>{call.decision.managerName}</span>
                <time dateTime={call.decision.decidedAt}>
                  {formatDate(call.decision.decidedAt)}
                </time>
              </p>
            </Panel>
          )}
        </>
      )}
    </>
  )
}
