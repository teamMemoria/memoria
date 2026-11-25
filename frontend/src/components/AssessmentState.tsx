import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Panel } from './controls'
import type { CallReview } from '../types/callReview'

export function AssessmentState({ call, transcript, children }: {
  call: CallReview
  transcript?: string
  children: ReactNode
}) {
  if (call.status === 'unavailable') {
    return (
      <Panel title="Assessment unavailable">
        <p>No assessment is stored for this conversation. This is not an Agent performance result.</p>
        {transcript && call.transcript && <Link to={transcript}>Transcript</Link>}
      </Panel>
    )
  }
  if (call.status === 'processing') {
    return (
      <Panel title="Feedback is processing">
        <p role="status">{transcript ? 'Automatic feedback is not ready for this call.' : 'Assessment results are not ready.'}</p>
        {transcript && <Link to={transcript}>Transcript</Link>}
      </Panel>
    )
  }
  return (
    <>
      {call.status === 'partial' && (
        <Panel title="Assessment incomplete">
          <p role="status">Processing failed for part of this assessment. Available checks are shown below; feedback is not ready.</p>
        </Panel>
      )}
      {children}
    </>
  )
}
