import { useRef, useState } from 'react'
import { checkTurns, type AssessmentData } from '../assessment-shared/assessment'
import { presentCommunication } from './presenter'

export function useCommunication(data: AssessmentData) {
  const { checks, phrases } = presentCommunication(data)
  const [selected, setSelected] = useState(
    checks.flatMap(checkTurns)[0] ?? data.turns[0]?.number,
  )
  const evidence = useRef<HTMLElement>(null)
  function selectTurn(turn: number) {
    setSelected(turn)
    const target = evidence.current?.querySelector<HTMLButtonElement>(
      `[data-turn="${turn}"]`,
    )
    target?.focus({ preventScroll: true })
    target?.scrollIntoView({
      block: 'center',
      inline: 'center',
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
        ? 'instant'
        : 'smooth',
    })
  }
  return { checks, phrases, selected, setSelected, evidence, selectTurn }
}
