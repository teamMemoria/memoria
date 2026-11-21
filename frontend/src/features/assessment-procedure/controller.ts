import { useState } from 'react'
import type { AssessmentData } from '../assessment-shared/assessment'
import { presentProcedure } from './presenter'

export function useProcedure(data: AssessmentData) {
  const initial = presentProcedure(data, undefined)
  const [activeNumber, setActiveNumber] = useState(initial.actions[0]?.number)
  return { ...presentProcedure(data, activeNumber), setActiveNumber }
}
