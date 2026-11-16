import { useEffect, useRef } from 'react'
import type { TranscriptTurn } from '../../../types/callReview'

export function useWaveformDock(transcript: TranscriptTurn[]) {
  const waveform = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const strip = waveform.current!
    const turns = Array.from(
      strip.querySelectorAll<HTMLElement>('.waveform-turn'),
    )
    const reduced = window.matchMedia(
      '(prefers-reduced-motion: reduce), (hover: none)',
    )
    let target: number | null = null
    let position = 0
    let strength = 0
    let frame = 0
    let previousTime = 0

    function paint() {
      turns.forEach((turn, index) => {
        const distance = Math.min(Math.abs(index - position) / 3, 1)
        const proximity = ((1 + Math.cos(distance * Math.PI)) / 2) * strength
        turn.style.setProperty('--wave-grow', String(1 + proximity * 0.8))
        turn.style.setProperty('--wave-scale', String(1 + proximity * 0.55))
      })
    }
    function animate(time: number) {
      const elapsed = Math.min(previousTime ? time - previousTime : 16, 32)
      previousTime = time
      // Frame-based easing follows the pointer without stacked CSS transition delays.
      if (target !== null)
        position += (target - position) * (1 - Math.exp(-elapsed / 26))
      const goal = target === null ? 0 : 1
      strength +=
        (goal - strength) * (1 - Math.exp(-elapsed / (goal ? 38 : 75)))
      if (
        Math.abs(goal - strength) < 0.001 &&
        (target === null || Math.abs(target - position) < 0.001)
      ) {
        strength = goal
        paint()
        frame = 0
        previousTime = 0
      } else {
        paint()
        frame = requestAnimationFrame(animate)
      }
    }
    function aim(next: number | null) {
      if (reduced.matches) return
      if (strength === 0 && next !== null) position = next
      target = next
      if (!frame) frame = requestAnimationFrame(animate)
    }
    function move(event: PointerEvent) {
      if (event.pointerType === 'touch') return
      const hovered = (event.target as Element).closest<HTMLElement>(
        '.waveform-turn',
      )
      if (hovered && turns.includes(hovered)) aim(turns.indexOf(hovered))
    }
    const leave = () => aim(null)
    function focus(event: FocusEvent) {
      const turn = event.target as HTMLElement
      if (turn.matches(':focus-visible') && turns.includes(turn))
        aim(turns.indexOf(turn))
    }
    function reset() {
      cancelAnimationFrame(frame)
      frame = previousTime = strength = 0
      target = null
      paint()
    }
    strip.addEventListener('pointermove', move)
    strip.addEventListener('pointerleave', leave)
    strip.addEventListener('focusin', focus)
    strip.addEventListener('focusout', leave)
    reduced.addEventListener('change', reset)
    return () => {
      reset()
      strip.removeEventListener('pointermove', move)
      strip.removeEventListener('pointerleave', leave)
      strip.removeEventListener('focusin', focus)
      strip.removeEventListener('focusout', leave)
      reduced.removeEventListener('change', reset)
    }
  }, [transcript])
  return waveform
}
