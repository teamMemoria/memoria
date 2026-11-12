import { useCallback, useEffect, useRef, useState } from 'react'
import type { TranscriptTurn, NarrationLoader } from '../../../types/callReview'

// Demo casting conventions, never identity facts or assessment inputs.
const feminineNames = new Set(
  'amy anne betty carol jackie janice karen molly rebecca sher stephanie summer'.split(
    ' ',
  ),
)
const masculineNames = new Set(
  'adam bob danny donny ford jack james joe john johnny mike peter richard rufold'.split(
    ' ',
  ),
)
export const demoVoices = {
  Agent: { feminine: 'af_bella', masculine: 'am_michael' },
  Customer: { feminine: 'af_heart', masculine: 'am_fenrir' },
} as const
export type VoiceStyle = 'feminine' | 'masculine'

export function voiceAssignment(
  name: string | undefined,
  fallback: VoiceStyle,
) {
  const first = name?.trim().split(/\s+/)[0].toLowerCase() ?? ''
  const style = feminineNames.has(first)
    ? 'feminine'
    : masculineNames.has(first)
      ? 'masculine'
      : fallback
  return {
    style,
    matched: feminineNames.has(first) || masculineNames.has(first),
  }
}

export function useTranscriptSpeech(
  turns: TranscriptTurn[],
  agent: VoiceStyle,
  customer: VoiceStyle,
  loadNarration?: NarrationLoader,
) {
  const [enabled, setEnabled] = useState(false)
  const [speaking, setSpeaking] = useState<number | null>(null)
  const [error, setError] = useState('')
  const enabledRef = useRef(false)
  const requested = useRef<number | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const run = useRef(0)
  const player = useRef<HTMLAudioElement | null>(null)
  const pending = useRef<AbortController | null>(null)
  const objectUrl = useRef<string | null>(null)
  const clips = useRef(new Map<string, Blob>())
  const loader = useRef(loadNarration)
  useEffect(() => {
    loader.current = loadNarration
  }, [loadNarration])
  const unavailable =
    typeof window.Audio !== 'function' || !loadNarration
      ? 'Natural voice playback is unavailable here.'
      : ''

  const stop = useCallback(() => {
    run.current += 1
    if (timer.current !== null) clearTimeout(timer.current)
    timer.current = null
    requested.current = null
    pending.current?.abort()
    pending.current = null
    if (player.current) {
      player.current.onplaying =
        player.current.onended =
        player.current.onerror =
          null
      player.current.onpause = player.current.onwaiting = null
      player.current.pause()
      player.current.removeAttribute('src')
      player.current.load()
    }
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    objectUrl.current = null
    setSpeaking(null)
  }, [])
  useEffect(() => {
    const cachedClips = clips.current
    const hide = () => {
      if (document.visibilityState === 'hidden') stop()
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') stop()
    }
    window.addEventListener('blur', stop)
    document.addEventListener('visibilitychange', hide)
    document.addEventListener('keydown', escape)
    return () => {
      enabledRef.current = false
      stop()
      cachedClips.clear()
      window.removeEventListener('blur', stop)
      document.removeEventListener('visibilitychange', hide)
      document.removeEventListener('keydown', escape)
    }
  }, [stop, turns])

  function fail(message = 'Playback failed. Click Demo voice to retry.') {
    stop()
    enabledRef.current = false
    setEnabled(false)
    setError(message)
  }
  async function play(turn: TranscriptTurn) {
    if (!enabledRef.current || requested.current !== turn.number) return
    const canonical = turns.find(
      (item) =>
        item.number === turn.number &&
        item.text === turn.text &&
        item.speaker === turn.speaker,
    )
    if (!canonical || canonical.speaker === 'System action') {
      fail('Natural voice is unavailable for this passage.')
      return
    }
    const token = run.current
    const voice =
      demoVoices[canonical.speaker][
        canonical.speaker === 'Agent' ? agent : customer
      ]
    const key = JSON.stringify([
      canonical.number,
      canonical.text,
      canonical.speaker,
      voice,
    ])
    const controller = new AbortController()
    pending.current = controller
    const timeout = setTimeout(() => controller.abort(), 15000)
    try {
      let blob = clips.current.get(key)
      if (!blob) {
        blob = await loader.current!(canonical, voice, controller.signal)
        if (run.current !== token) return
        if (blob.type !== 'audio/mpeg' || blob.size === 0)
          throw new Error('Invalid narration audio.')
        clips.current.set(key, blob)
      }
      if (run.current !== token) return
      if (!player.current) player.current = new Audio()
      const audio = player.current
      objectUrl.current = URL.createObjectURL(blob)
      audio.setAttribute('src', objectUrl.current)
      audio.onplaying = () => {
        if (run.current === token) setSpeaking(turn.number)
      }
      audio.onended = () => {
        if (run.current === token) setSpeaking(null)
      }
      audio.onpause = audio.onwaiting = () => {
        if (run.current === token) setSpeaking(null)
      }
      audio.onerror = () => {
        if (run.current === token) fail()
      }
      await audio.play()
    } catch (error) {
      if (run.current === token)
        fail(
          error instanceof Error && error.name !== 'AbortError'
            ? `${error.message} Click Demo voice to retry.`
            : 'Playback timed out. Click Demo voice to retry.',
        )
    } finally {
      clearTimeout(timeout)
      if (pending.current === controller) pending.current = null
    }
  }
  function preview(turn: TranscriptTurn, immediate = false) {
    if (!enabledRef.current || unavailable) return
    if (turn.speaker === 'System action' || !turn.text.trim()) {
      stop()
      return
    }
    if (
      requested.current === turn.number &&
      (!immediate || timer.current === null)
    )
      return
    stop()
    requested.current = turn.number
    if (immediate) void play(turn)
    else
      timer.current = setTimeout(() => {
        timer.current = null
        void play(turn)
      }, 300)
  }
  function toggle(turn: TranscriptTurn | undefined) {
    if (unavailable) return
    const next = !enabledRef.current
    stop()
    enabledRef.current = next
    setEnabled(next)
    setError('')
    if (next) {
      // Unlock this single reusable media element in the user's gesture (Safari).
      if (!player.current) player.current = new Audio()
      const audio = player.current
      audio.setAttribute(
        'src',
        'data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQIAAAAAAA==',
      )
      void audio.play().catch(() => {})
      if (turn) preview(turn, true)
    }
  }
  return {
    enabled,
    speaking,
    player,
    error,
    unavailable,
    toggle,
    preview,
    stop,
  }
}
