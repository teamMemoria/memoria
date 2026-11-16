import { useEffect, useState, type CSSProperties } from 'react'
import type { TranscriptTurn, NarrationLoader } from '../../../types/callReview'
import { EvidenceLink } from '../../assessment-shared/AssessmentElements'
import type { EvidenceHandler } from '../../assessment-shared/assessment'
import { useWaveformDock } from './useWaveformDock'
import { useTranscriptSpeech, voiceAssignment } from './useTranscriptSpeech'
import './waveform.css'

// The original visual represents word lengths. It never represents recorded sound.
export function TranscriptWaveform({
  turns,
  agentName,
  loadNarration,
  selected,
  onSelect,
  onOpen,
}: {
  turns: TranscriptTurn[]
  agentName: string
  loadNarration?: NarrationLoader
  selected: number | undefined
  onSelect: (turn: number) => void
  onOpen: EvidenceHandler
}) {
  const [preview, setPreview] = useState<number | null>(null)
  const agentVoice = voiceAssignment(agentName, 'masculine').style
  // There is no customer-profile field; retain the existing demo voice assignment.
  const audio = useTranscriptSpeech(
    turns,
    agentVoice,
    'feminine',
    loadNarration,
  )
  const dock = useWaveformDock(turns)
  useEffect(() => {
    if (audio.speaking === null) return
    const element = dock.current?.querySelector<HTMLElement>(
      `[data-turn="${audio.speaking}"]`,
    )
    let frame = 0
    function update() {
      const player = audio.player.current
      if (!element || !player) return
      const progress =
        Number.isFinite(player.duration) && player.duration > 0
          ? Math.min(1, player.currentTime / player.duration)
          : 0
      element.style.setProperty('--voice-progress', String(progress))
      if (!player.paused && !player.ended) frame = requestAnimationFrame(update)
    }
    update()
    return () => {
      cancelAnimationFrame(frame)
      element?.style.removeProperty('--voice-progress')
    }
  }, [audio.speaking, audio.player, dock])
  function selectTurn(turn: TranscriptTurn) {
    onSelect(turn.number)
    audio.preview(turn, true)
  }
  const data = turns.map((turn) => ({
    ...turn,
    words: turn.text.match(/\S+/g) ?? [],
  }))
  const longest = Math.max(
    1,
    ...data.flatMap((turn) => turn.words.map((word) => word.length)),
  )
  const active =
    data.find(
      (turn) => turn.number === (audio.speaking ?? preview ?? selected),
    ) ?? data[0]
  return (
    <>
      <div className="section-heading waveform-heading">
        <h2>Evidence</h2>
        <div className="waveform-tools">
          <span className="chart-legend">
            <i />
            Agent
            <span className="legend-customer" />
            Customer
            <span className="legend-action" />
            Action
          </span>
          <button
            className="waveform-voice"
            aria-pressed={audio.enabled}
            aria-label={audio.enabled ? 'Mute demo voice' : 'Enable demo voice'}
            disabled={!!audio.unavailable}
            title="Generated narration. Enable, then hover, focus or tap a turn to listen."
            onClick={() => audio.toggle(active)}
          >
            <span
              aria-hidden="true"
              className={`codicon codicon-${audio.enabled ? 'unmute' : 'mute'}`}
            />
            Demo voice
          </button>
        </div>
      </div>
      {(audio.unavailable || audio.error) && (
        <p className="waveform-voice-error" role="status">
          {audio.error || audio.unavailable}
        </p>
      )}
      <div
        className="waveform-scroll"
        role="group"
        aria-label="Transcript turns"
        data-voice-enabled={audio.enabled}
        onMouseLeave={() => {
          setPreview(null)
          audio.stop()
        }}
      >
        <div className="transcript-waveform" ref={dock}>
          {data.map((turn) => (
            <button
              key={turn.number}
              className={`waveform-turn waveform-turn--${turn.speaker === 'System action' ? 'action' : turn.speaker.toLowerCase()} ${turn.number === active?.number ? 'waveform-turn--active' : ''} ${turn.number === selected ? 'waveform-turn--selected' : ''}`}
              data-turn={turn.number}
              data-speaking={turn.number === audio.speaking}
              style={
                {
                  '--turn-width': `${Math.max(34, turn.words.length * 5 + 6)}px`,
                  '--turn-weight': Math.max(1, turn.words.length),
                } as CSSProperties
              }
              aria-pressed={turn.number === selected}
              aria-label={`View turn ${turn.number}, ${turn.speaker}, ${turn.words.length} words`}
              onMouseMove={() => {
                setPreview(turn.number)
                audio.preview(turn)
              }}
              onMouseLeave={audio.stop}
              onFocus={() => {
                setPreview(turn.number)
                audio.preview(turn)
              }}
              onBlur={() => {
                setPreview(null)
                audio.stop()
              }}
              onClick={() => selectTurn(turn)}
            >
              <span className="waveform-bars" aria-hidden="true">
                {turn.words.map((word, index) => (
                  <i
                    key={index}
                    style={
                      {
                        height: `${10 + (word.length / longest) * 90}%`,
                        '--voice-delay': `${index * 57}ms`,
                      } as CSSProperties
                    }
                  />
                ))}
              </span>
              {audio.speaking === turn.number && (
                <span className="waveform-playhead" aria-hidden="true">
                  <i />
                </span>
              )}
              <span className="waveform-turn-label">
                {turn.number}
                {audio.speaking === turn.number && (
                  <span aria-hidden="true" className="codicon codicon-unmute" />
                )}
              </span>
            </button>
          ))}
        </div>
      </div>
      {active ? (
        <div
          className="waveform-preview"
          role="region"
          aria-label="Selected transcript turn"
          aria-live={audio.enabled ? 'off' : 'polite'}
        >
          <span>
            {active.speaker} · Turn {active.number}
            {active.time ? ` · ${active.time}` : ''}
          </span>
          <blockquote>{active.text}</blockquote>
          <EvidenceLink turns={[active.number]} onOpen={onOpen}>
            View context
          </EvidenceLink>
        </div>
      ) : (
        <p className="quiet-note">Transcript unavailable.</p>
      )}
      <details className="chart-data">
        <summary>View transcript data</summary>
        <div className="chart-data-list">
          {data.map((turn) => (
            <button key={turn.number} onClick={() => selectTurn(turn)}>
              Turn {turn.number}
              <span>{turn.speaker}</span>
              <strong>{turn.words.length} words</strong>
            </button>
          ))}
        </div>
      </details>
    </>
  )
}
