import { CountBar } from '../../components/CountBar'
import type { Conversation } from './conversations'
import { scoreBand, scoreBands, type ScoreBand } from './scoreBands'

export function ConversationScoreBar({ records, selected, onPreview, onSelect }: {
  records: Pick<Conversation, 'simulationScore'>[]
  selected: ScoreBand | null
  onPreview: (band: ScoreBand | null) => void
  onSelect: (band: ScoreBand | 'all') => void
}) {
  const recordBands = records.map(({ simulationScore }) => scoreBand(simulationScore))
  const segments = scoreBands.map((band) => ({
    ...band,
    count: recordBands.filter((value) => value === band.value).length,
  }))

  return (
    <section className="conversation-score-summary" aria-label="Score distribution">
      <CountBar
        label="Conversation score bands"
        segments={segments}
        selected={selected}
        onPreview={onPreview}
        onSelect={(band) => onSelect(band === selected ? 'all' : band)}
      />
      <p className="metadata-line">{records.length} {records.length === 1 ? 'conversation' : 'conversations'}</p>
    </section>
  )
}
