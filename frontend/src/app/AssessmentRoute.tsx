import { Link, useParams } from 'react-router'
import { ApprovedReference } from '../components/ApprovedReference'
import { Button, Panel, StatusLabel } from '../components/controls'
import { useCallReview } from '../lib/useCallReview'
import { auditResults } from '../types/callReview'
import type { CallApi, ManagerCallApi } from '../types/callReview'
import { canReadKnowledge } from '../types/knowledge'
import type { Viewer } from '../types/viewer'

// Read the existing API contract. Scores, calculations and new evidence
// contracts belong to the separate assessment integration.
export function AssessmentRoute({ viewer, api, managerApi }: {
  viewer: Viewer
  api: CallApi | null
  managerApi: ManagerCallApi | null
}) {
  const { conversationId = '', category = '' } = useParams()
  const state = useCallReview(
    viewer.role === 'agent' ? api : null, viewer.id, conversationId,
    viewer.role === 'manager' ? managerApi : null,
  )
  const base = `/${viewer.role}/conversations/${encodeURIComponent(conversationId)}`
  if (state.status === 'loading') return <p role="status">Loading assessment…</p>
  if (state.status === 'error') return <Panel title="Unable to load assessment">
    <p role="alert">Please try again.</p><Button onClick={state.retry}>Try again</Button>
  </Panel>
  if (state.status === 'unavailable') return <Panel title="Conversation unavailable">
    <p>This conversation is not available in your workspace.</p>
  </Panel>
  const { call } = state
  const criterion = call.criteria.find((item) => item.id === category)
  if (!criterion) return <Panel title="Assessment unavailable"><Link to={base}>Back to conversation</Link></Panel>
  const findings = call.findings.filter((item) => item.criterionId === category)
  const turns = call.transcript?.turns ?? []
  const cited = new Set([...criterion.evidenceTurnNumbers, ...findings.flatMap((item) => item.evidenceTurnNumbers)])
  const references = new Set([criterion.referenceId, ...findings.map((item) => item.referenceId)])
  const result = auditResults[criterion.result]
  return <div className="call-overview">
    <Link to={base}>Back to conversation</Link>
    <h1>{criterion.title}</h1>
    <p>Call {call.id} · {call.agentName}</p>
    {call.status === 'processing' ? <p role="status">Assessment results are not ready.</p> : <>
      <Panel title="Recorded assessment">
        <StatusLabel tone={result.tone}>{result.label}</StatusLabel>
        <p>{criterion.explanation}</p>
        {category === 'communication-style' && <p>Wording only; vocal tone is not assessed.</p>}
      </Panel>
      {findings.map((finding) => <Panel key={finding.id} title={finding.title}>
        <p>{finding.explanation}</p><p>{finding.suggestion}</p>
        <Link to={`${base}/findings/${encodeURIComponent(finding.id)}`}>
          {viewer.role === 'agent' ? 'Add context or request review' : 'Review decision'}
        </Link>
      </Panel>)}
      <Panel title="Cited conversation evidence">
        {turns.filter((turn) => cited.has(turn.number)).map((turn) => <figure key={turn.number}>
          <blockquote>{turn.text}</blockquote><figcaption>Turn {turn.number} · {turn.speaker}</figcaption>
        </figure>)}
        {!turns.some((turn) => cited.has(turn.number)) && <p>No cited passages are available for this assessment.</p>}
        {[...cited].filter((number) => !turns.some((turn) => turn.number === number)).map((number) =>
          <p key={number}>Cited turn {number} is unavailable in the supplied transcript.</p>)}
      </Panel>
      {call.references.filter((entry) => references.has(entry.id) && canReadKnowledge(entry, call.agentId)).map((entry) =>
        <Panel key={entry.id} title={entry.title}><ApprovedReference entry={entry} /></Panel>)}
    </>}
    <Panel title="Transcript">
      {!call.transcript?.complete && <p>{call.transcript?.unavailableReason ?? 'The complete transcript is not available.'}</p>}
      {turns.map((turn) => <p key={turn.number}><strong>Turn {turn.number} · {turn.speaker}: </strong>{turn.text}</p>)}
    </Panel>
    {call.decision && <Panel title="Manager decision">
      <p>{call.decision.outcome}: {call.decision.reason}</p><p>{call.decision.feedback}</p>
      <p>This decision is separate from the recorded assessment.</p>
    </Panel>}
  </div>
}
