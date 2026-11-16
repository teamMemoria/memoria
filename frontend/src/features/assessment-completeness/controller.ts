import { useState } from 'react'
import type { AssessmentData } from '../assessment-shared/assessment'
import { presentCompleteness } from './presenter'

export function useCompleteness(data: AssessmentData) {
  const [selection, setSelection] = useState<string | undefined>(data.call.requestLinks?.[0]?.id)
  const view = presentCompleteness(data, selection)
  function selectResponse(turn: number) {
    setSelection(view.answered.find((request) => request.responseTurns.includes(turn))?.id)
  }
  return { ...view, setSelection, selectResponse }
}
