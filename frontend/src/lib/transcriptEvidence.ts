import type { CallReview } from '../types/callReview'

export function transcriptEvidence(
  transcript: CallReview['transcript'],
  numbers: readonly number[],
  scope: 'selected' | 'surrounding' | 'full' = 'selected',
) {
  const recorded = transcript?.turns ?? []
  const selected = new Set(numbers)
  const available = new Set(recorded.map(({ number }) => number))
  // Surrounding entries follow the retained recording order, even when turns are missing.
  const turns = scope === 'full' ? recorded : recorded.filter((turn, index) =>
    selected.has(turn.number) || (scope === 'surrounding' && (
      selected.has(recorded[index - 1]?.number) || selected.has(recorded[index + 1]?.number)
    )),
  )
  return { turns, missing: numbers.filter((number) => !available.has(number)), selected }
}
