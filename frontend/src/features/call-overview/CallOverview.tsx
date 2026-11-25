import { conversationFilters } from '../../lib/workspaceSearch'
import type { ReactNode } from 'react'
import { AssessmentState } from '../../components/AssessmentState'
import { formatDate } from '../../lib/dates'
import { ResourceNotice } from '../../components/ResourceNotice'
import { ConversationMetadata } from '../../components/ConversationMetadata'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { Icon } from '../../components/Icon'
import { Button, Panel, StatusLabel } from '../../components/controls'
import { useCallReview } from '../../lib/useCallReview'
import { assessmentData, categories, checkTitle, linkedCheckTurns } from '../assessment-shared/assessment'
import { scoreTone } from '../conversations/scoreBands'
import { assessmentPercentage, decisionOutcomes, pilotLabel, percentage, auditResults as results } from '../../types/callReview'
import type {
  AuditCriterion,
  CallApi,
  CallReview,
  ManagerCallApi,
} from '../../types/callReview'
import type { Viewer } from '../../types/viewer'
import './call-overview.css'

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
  const backParams = conversationFilters(params)
  const search = backParams.size ? `?${backParams}` : ''
  const startAnalysis = viewer.role === 'manager' ? managerApi?.startAnalysis : undefined

  return (
    <div className="call-overview">
      <Link
        className="call-overview-back inline-center"
        to={`/${viewer.role}/conversations${search}`}
      >
        Conversations
      </Link>
      {state.status === 'ready' ? (
        <>
          <CallContent
            key={state.call.id}
            call={state.call}
            search={search}
            role={viewer.role}
          />
          {startAnalysis && !state.call.assessmentVersion && (
            <PilotAnalysis
              key={state.call.id}
              start={() => startAnalysis(viewer.id, state.call.id)}
              refresh={state.retry}
            />
          )}
        </>
      ) : (
        <div className="call-overview-state">
          <h1>Call overview</h1>
          <ResourceNotice state={state} loading="Loading conversation…" errorTitle="Unable to load conversation"
            error="Your conversation could not be loaded. Please try again."
            unavailableTitle="Conversation unavailable"
            unavailable={api ? 'This conversation is not available in your workspace.' : 'Conversation data is not connected.'} />
        </div>
      )}
    </div>
  )
}

function PilotAnalysis({ start, refresh }: { start: () => Promise<unknown>; refresh: () => void }) {
  const [state, setState] = useState<'idle' | 'starting' | 'queued' | 'failed'>('idle')

  async function run() {
    setState('starting')
    try {
      await start()
      setState('queued')
    } catch {
      setState('failed')
    }
  }

  return (
    <Panel title="Pilot assessment">
      {state === 'queued' ? (
        <Button variant="secondary" onClick={refresh}>Refresh assessment</Button>
      ) : (
        <Button variant="secondary" onClick={() => void run()} disabled={state === 'starting'}>
          {state === 'starting' ? 'Starting…' : 'Run pilot assessment'}
        </Button>
      )}
      {state === 'failed' && <p role="alert">The assessment could not be started.</p>}
    </Panel>
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
  const simulation = call.assessmentSource === 'simulation'
  const criteria = simulation
    ? categories.flatMap(({ id, title }) => {
        const criterion = call.criteria.find((item) => item.id === id)
        return criterion ? [{ ...criterion, title }] : []
      })
    : call.criteria
  const base = `/${role}/conversations/${encodeURIComponent(call.id)}`
  const transcriptParams = new URLSearchParams(search)
  transcriptParams.set('transcript', 'full')
  const transcript =
    role === 'agent' && !simulation
      ? `${base}/transcript${search}`
      : `${base}/assessments/procedure?${transcriptParams}`
  const highlights = simulation ? criteria.flatMap((criterion) => {
    const data = assessmentData(call, criterion.id)
    return data.checks.flatMap((check) => {
      if (!check.critical && check.outcome !== 'breach' && check.outcome !== 'partial') return []
      const turns = linkedCheckTurns(data, check)
      return turns.length ? [{ criterion, check, turns }] : []
    })
  }) : []
  const highlight = highlights.find(({ check }) => check.critical)
    ?? highlights.find(({ check }) => check.outcome === 'breach')
    ?? highlights[0]
  const highlightParams = new URLSearchParams(search)
  if (highlight) {
    highlightParams.set('evidence', highlight.turns.map((turn) => turn.number).join(','))
    highlightParams.set('check', highlight.check.id)
  }

  function evidenceLink(criterion: AuditCriterion) {
    return `${base}/assessments/${criterion.id}${search}`
  }

  return (
    <>
      <h1>{call.topic}</h1>
      <ConversationMetadata call={call} sourceId={call.sourceId} />
      {!simulation && pilotLabel(call) && <p className="metadata-line">{pilotLabel(call)}</p>}
      {!simulation && <p className="call-overview-summary">{call.summary}</p>}
      <AssessmentState call={call} transcript={transcript}>
        <section className={simulation ? 'call-audit call-audit--simulation' : 'call-audit'} aria-label={simulation ? 'Assessment scores' : 'Automatic feedback'}>
          <div className="call-audit-diagram">
            <div className="call-audit-root flex-center panel-frame" data-score-tone={simulation ? scoreTone(call.overallScoring?.score) : undefined}>
              <span className="call-audit-phone">
                <Icon name="phone" size={24} />
              </span>
              {simulation ? (
                <span className="call-audit-overall">
                  <span>Overall score</span>
                  <strong>{percentage(call.overallScoring?.score)}</strong>
                </span>
              ) : (
                <span>{call.overallScoring
                  ? `Overall ${call.criteria.some(({ scoring }) => scoring?.coverage === 0)
                    ? 'Cannot assess'
                    : assessmentPercentage(call.overallScoring)}`
                  : call.id}</span>
              )}
            </div>
            <div className="call-criteria">
              {criteria.map((criterion) => {
                const result = simulation ? null : results[criterion.result]
                const outcome = simulation
                  ? percentage(criterion.scoring?.score)
                  : criterion.scoring ? assessmentPercentage(criterion.scoring) : result?.label
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
                      {outcome}
                    </span>
                    {criterion.scoring && <span className="call-criterion-qualification">Coverage: {percentage(criterion.scoring.coverage, 'Unknown')}</span>}
                  </>
                )
                const connectionTone =
                  result?.tone === 'attention'
                    ? 'attention'
                    : result?.tone === 'positive' &&
                        criterion.id === 'communication-style'
                      ? 'positive'
                      : 'neutral'
                return (
                  <div
                    className={`call-criterion-column call-criterion-column--${connectionTone}`}
                    data-score-tone={simulation ? scoreTone(criterion.scoring?.score) : undefined}
                    key={criterion.id}
                  >
                    <Link
                      className={`call-criterion flex-center panel-frame call-criterion--${result?.tone ?? 'neutral'}`}
                      to={evidenceLink(criterion)}
                      aria-label={`${criterion.title}: ${outcome}`}
                    >
                      {cardContent}
                    </Link>
                  </div>
                )
              })}
            </div>
          </div>
        </section>
        {highlight ? (
          <FindingStrip label="Key evidence" title="Key evidence" transcript={transcript}
            action="View evidence" to={`${base}/assessments/${highlight.criterion.id}?${highlightParams}`}>
            <p>{checkTitle(highlight.check)}</p>
          </FindingStrip>
        ) : simulation && <Link className="button button--secondary" to={transcript}>Transcript</Link>}
        {call.findings.length > 0 && (
          <FindingStrip label="Automated findings" transcript={transcript} action="View feedback"
            title={`${call.findings.length} automated ${call.findings.length === 1 ? 'finding' : 'findings'}`}
            to={`${base}/findings/${encodeURIComponent(call.findings[0].id)}${search}`}>
            {call.findings.map((finding) => <p key={finding.id}>{finding.title}</p>)}
          </FindingStrip>
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
              {decisionOutcomes[call.decision.outcome].label}
            </StatusLabel>
            <p>{call.decision.reason}</p>
            <h3>Feedback</h3>
            <p>{call.decision.feedback}</p>
            <p className="call-overview-decision-meta metadata-line">
              <span>{call.decision.managerName}</span>
              <time dateTime={call.decision.decidedAt}>
                {formatDate(call.decision.decidedAt, 'Date not recorded')}
              </time>
            </p>
          </Panel>
        )}
      </AssessmentState>
    </>
  )
}

function FindingStrip({ label, title, transcript, action, to, children }: {
  label: string
  title: string
  transcript: string
  action: string
  to: string
  children: ReactNode
}) {
  return (
    <section className="call-finding-strip flex-center panel-frame" aria-label={label}>
      <span className="call-finding-marker"><Icon name="info" size={24} /></span>
      <div className="call-finding-copy grid-layout"><h2>{title}</h2>{children}</div>
      <div className="call-finding-actions flex-center">
        <Link className="button button--primary" to={to}>{action}</Link>
        <Link className="button button--secondary" to={transcript}>Transcript</Link>
      </div>
    </section>
  )
}
