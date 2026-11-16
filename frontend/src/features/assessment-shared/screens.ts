import type { ComponentType } from 'react'
import type { CriterionId } from '../../types/callReview'
import type { ScreenProps } from './assessment'

type Registration = { id: CriterionId; Screen: ComponentType<ScreenProps> }
// Each feature supplies its own registration; missing features keep the generic route.
const modules = import.meta.glob<{ default: Registration }>(
  '../assessment-*/screen.ts',
  { eager: true },
)
export const screens: Partial<Record<CriterionId, ComponentType<ScreenProps>>> =
  Object.fromEntries(
    Object.values(modules).map(({ default: entry }) => [
      entry.id,
      entry.Screen,
    ]),
  )
