import { useState } from 'react'
import type { AssessmentData } from '../assessment-shared/assessment'
import { presentAnswer } from './presenter'

export function useAnswer(data: AssessmentData) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  return { ...presentAnswer(data, selectedId), setSelectedId }
}
