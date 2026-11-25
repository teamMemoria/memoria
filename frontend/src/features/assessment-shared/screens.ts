import type { ComponentType } from 'react'
import type { CriterionId } from '../../types/callReview'
import { AnswerScreen } from '../assessment-answer-support/AnswerScreen'
import { CommunicationScreen } from '../assessment-communication-style/CommunicationScreen'
import { CompletenessScreen } from '../assessment-completeness/CompletenessScreen'
import { ProcedureScreen } from '../assessment-procedure/ProcedureScreen'
import type { ScreenProps } from './assessment'

export const screens: Record<CriterionId, ComponentType<ScreenProps>> = {
  procedure: ProcedureScreen,
  'answer-support': AnswerScreen,
  completeness: CompletenessScreen,
  'communication-style': CommunicationScreen,
}
