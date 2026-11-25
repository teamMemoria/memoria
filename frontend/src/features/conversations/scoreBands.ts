import type { Conversation } from './conversations'

export const scoreBands = [
  { value: 'high', min: 80, label: '80–100%', tone: 'positive' },
  { value: 'middle', min: 60, label: '60–79%', tone: 'attention' },
  { value: 'low', min: 0, label: 'Below 60%', tone: 'negative' },
] as const

export type ScoreBand = (typeof scoreBands)[number]['value']

export const scoreOptions = [
  ['all', 'All scores'] as const,
  ...scoreBands.map(({ value, label }) => [value, label] as const),
]

export const scoreColumns = [
  { label: 'Call', width: 18 },
  { label: 'Agent', width: 20 },
  { label: 'Topic', width: 34 },
  { label: 'Overall', width: 28, sort: 'descending' },
] as const

export function scoreBandFrom(value: string | null) {
  return scoreBands.find((band) => band.value === value)?.value ?? null
}

function bandForScore(score: number | null | undefined) {
  return score == null ? undefined : scoreBands.find(({ min }) => Math.round(score) >= min)
}

export function scoreBand(score: number | undefined) {
  return bandForScore(score)?.value
}

export function scoreTone(score: number | null | undefined) {
  return bandForScore(score)?.tone
}

export function rankByScore<T extends Pick<Conversation, 'simulationScore'>>(
  records: T[],
  band: ScoreBand | null,
) {
  return records
    .filter((record) => !band || scoreBand(record.simulationScore) === band)
    .sort((first, second) => (second.simulationScore ?? -1) - (first.simulationScore ?? -1))
}
