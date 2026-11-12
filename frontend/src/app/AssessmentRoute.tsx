import { screens } from '../features/assessment-shared/screens'
import { DefaultAssessmentScreen } from '../features/assessment-shared/DefaultAssessmentScreen'
import { decisionOutcomes } from '../features/review-queue/teamQueue'
import { useEffect, useRef } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { Button, Panel, StatusLabel } from '../components/controls'
import { Icon } from '../components/Icon'
import { useCallReview } from '../lib/useCallReview'
import type {
  CallApi,
  CallReview,
  CriterionId,
  ManagerCallApi,
} from '../types/callReview'
import type { NarrationLoader } from '../types/callReview'
import type { Viewer } from '../types/viewer'
import { AssessmentNavigation } from '../features/assessment-shared/AssessmentNavigation'
import { EvidenceSheet } from '../features/assessment-shared/EvidenceSheet'
import {
  assessmentData,
  categories,
} from '../features/assessment-shared/assessment'
import '../features/assessment-shared/assessment.css'
import '../features/assessment-shared/shadcn.css'



export function AssessmentRoute({
  viewer,
  api,
  managerApi,
}: {
  viewer: Viewer
  api: CallApi | null
  managerApi: ManagerCallApi | null
}) {
  const { conversationId = '', category = '' } = useParams()
  const voiceApi = viewer.role === 'agent' ? api : managerApi
  const loadNarration: NarrationLoader = (turn, voice, signal) => {
    if (!voiceApi?.getNarration) return Promise.reject(new Error('Natural voice unavailable.'))
    return voiceApi.getNarration(viewer.id, conversationId, turn, voice, signal)
  }
  const state = useCallReview(
    viewer.role === 'agent' ? api : null,
    viewer.id,
    conversationId,
    viewer.role === 'manager' ? managerApi : null,
  )
  if (!categories.some((item) => item.id === category))
    return (
      <Panel title="Assessment unavailable">
        <p>Unknown category.</p>
      </Panel>
    )
  if (state.status === 'loading')
    return <p role="status">Loading assessment…</p>
  if (state.status === 'error')
    return (
      <Panel title="Unable to load assessment">
        <p role="alert">Please try again.</p>
        <Button onClick={state.retry}>Try again</Button>
      </Panel>
    )
  if (state.status === 'unavailable')
    return (
      <Panel title="Conversation unavailable">
        <p>This conversation is not available in your workspace.</p>
      </Panel>
    )
  return (
    <AssessmentContent
      key={`${viewer.id}-${state.call.id}-${category}`}
      call={state.call}
      role={viewer.role}
      category={category as CriterionId}
      loadNarration={voiceApi?.getNarration ? loadNarration : undefined}
    />
  )
}

function AssessmentContent({
  loadNarration,
  call,
  role,
  category,
}: {
  call: CallReview
  role: Viewer['role']
  loadNarration?: NarrationLoader
  category: CriterionId
}) {
  const [params, setParams] = useSearchParams()
  const trigger = useRef<HTMLElement | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const base = `/${role}/conversations/${encodeURIComponent(call.id)}`
  const backParams = new URLSearchParams()
  for (const key of ['q', 'status'])
    if (params.has(key)) backParams.set(key, params.get(key)!)
  const search = backParams.size ? `?${backParams}` : ''
  const turns = [
    ...new Set(
      (params.get('evidence') ?? '')
        .split(',')
        .filter(Boolean)
        .map(Number)
        .filter((number) => Number.isSafeInteger(number) && number > 0),
    ),
  ]
  const section =
    params.has('section') && /^\d+$/.test(params.get('section')!)
      ? Number(params.get('section'))
      : null
  const selection = {
    turns,
    section,
    referenceId: params.get('reference'),
    full: params.get('transcript') === 'full',
    checkId: params.get('check'),
  }
  const open =
    params.has('evidence') || params.has('reference') || params.has('check') || selection.full
  const initiallyOpen = useRef(open)
  useEffect(() => {
    window.scrollTo(0, 0)
    if (!initiallyOpen.current) heading.current?.focus({ preventScroll: true })
  }, [])

  function openEvidence(
    numbers: number[],
    referenceId?: string | null,
    step?: number | null,
    checkId?: string,
  ) {
    trigger.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    const next = new URLSearchParams(backParams)
    next.set('evidence', numbers.join(','))
    if (referenceId) next.set('reference', referenceId)
    if (step != null) next.set('section', String(step))
    if (checkId) next.set('check', checkId)
    setParams(next)
  }
  const data = assessmentData(call, category)
  const Screen = screens[category] ?? DefaultAssessmentScreen
  return (
    <div className="assessment-page">
      <Link className="detail-back" to={`${base}${search}`}>
        <Icon name="arrowLeft" />
        {call.topic && call.topic !== 'Unassigned' ? call.topic : 'Back to conversation'}
      </Link>
      <header className="assessment-heading">
        <div className="assessment-intro">
          <h1 ref={heading} tabIndex={-1}>
            {categories.find((item) => item.id === category)!.title}
          </h1>
          <ul className="call-overview-metadata" aria-label="Call details">
            <li>Call {call.id}{(call.sourceId ?? call.assessmentVersion?.sourceId) && ` · ABCD ${call.sourceId ?? call.assessmentVersion?.sourceId}`}</li>
            <li>{call.agentName}</li>
            <li>
              {call.transcript
                ? `${call.transcript.turns.length} ${call.transcript.complete ? '' : 'recorded '}${call.transcript.turns.length === 1 ? 'turn' : 'turns'}`
                : 'Turns unavailable'}
            </li>
          </ul>
        </div>
        <button
          className="transcript-shortcut"
          onClick={(event) => {
            trigger.current = event.currentTarget
            const next = new URLSearchParams(backParams)
            next.set('transcript', 'full')
            setParams(next)
          }}
        >
          <Icon name="document" />
          Full transcript
        </button>
      </header>
      <AssessmentNavigation
        metric={category}
        base={base}
        search={search}
        call={call}
      />
      {call.status === 'unavailable' ? (
        <Panel title="Assessment unavailable"><p>No assessment is stored for this conversation. This is not an Agent performance result.</p></Panel>
      ) : call.status === 'processing' ? (
        <Panel title="Feedback is processing">
          <p role="status">Assessment results are not ready.</p>
        </Panel>
      ) : (
        <div
          className={`metric-content ${(data.criterion?.result === 'needs-review' || data.checks.some((check) => check.outcome === 'breach')) ? 'metric-content--attention' : ''}`}
        >
          <Screen data={data} onOpen={openEvidence} loadNarration={loadNarration} />
        </div>
      )}
      <section className="assessment-actions" aria-label="Review actions">
        {data.findings.map((finding) => (
          <Link
            className="source-link"
            key={finding.id}
            to={`${base}/findings/${encodeURIComponent(finding.id)}${search}`}
          >
            {role === 'manager'
              ? 'Review decision'
              : 'Add context or request review'}
            : {finding.title}
            <Icon name="arrowRight" />
          </Link>
        ))}
        {role === 'agent' && !data.findings.length && (
          <Link className="source-link" to={`${base}/transcript${search}`}>
            Transcript and Agent context
          </Link>
        )}
        {call.decision && (
          <Panel title="Manager decision">
            <StatusLabel
              tone={
                call.decision.outcome === 'confirmed'
                  ? 'attention'
                  : call.decision.outcome === 'cannot-assess'
                    ? 'neutral'
                    : 'positive'
              }
            >
              {decisionOutcomes[call.decision.outcome].label}
            </StatusLabel>
            <p>{call.decision.reason}</p>
            <p>{call.decision.feedback}</p>
            <p className="metadata-line">
              {call.decision.managerName} · {call.decision.decidedAt}
            </p>
            <p>
              The Manager decision is separate from this automatic assessment.
            </p>
          </Panel>
        )}
      </section>
      <EvidenceSheet
        call={call}
        referenceIds={data.referenceIds}
        checks={data.checks}
        onSelect={openEvidence}
        selection={selection}
        open={open}
        onClose={() => setParams(backParams)}
        onFullTranscript={() => {
          const next = new URLSearchParams(params)
          next.set('transcript', 'full')
          setParams(next)
        }}
        restoreFocus={() => {
          if (trigger.current?.isConnected) trigger.current.focus()
          else document.querySelector<HTMLElement>('h1')?.focus()
        }}
      />
    </div>
  )
}
