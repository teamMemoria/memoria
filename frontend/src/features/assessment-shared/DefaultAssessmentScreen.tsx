import { Panel } from '../../components/controls'
import {
  ScoreCard,
  AssessmentSummary,
  EvidenceRows,
  MaterialLimits,
  EvidenceLink,
} from './AssessmentElements'
import type { ScreenProps } from './assessment'

// Existing routes remain useful while individual assessment designs are installed.
export function DefaultAssessmentScreen({ data, onOpen }: ScreenProps) {
  return (
    <>
      <ScoreCard data={data} label="Recorded assessment" />
      <Panel title="Recorded assessment">
        <AssessmentSummary data={data} onOpen={onOpen} />
      </Panel>
      <Panel title="Cited conversation evidence">
        <EvidenceRows data={data} onOpen={onOpen} />
      </Panel>
      {data.referenceIds.map((id) => (
        <EvidenceLink key={id} turns={[]} referenceId={id} onOpen={onOpen}>
          Reference {id}
        </EvidenceLink>
      ))}
      <MaterialLimits data={data} />
    </>
  )
}
