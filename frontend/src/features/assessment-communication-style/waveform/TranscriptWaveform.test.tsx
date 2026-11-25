import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TranscriptTurn, NarrationLoader } from '../../../types/callReview'
import { TranscriptWaveform } from './TranscriptWaveform'
import { useTranscriptSpeech, voiceAssignment } from './useTranscriptSpeech'

const turns: TranscriptTurn[] = [
  {
    number: 1,
    speaker: 'Customer',
    text: 'Hi [PERSON_1]. Please help with this order.',
    time: null,
  },
  { number: 2, speaker: 'System action', text: 'Lookup started.', time: null },
  { number: 3, speaker: 'Agent', text: 'Yes.', time: null },
]
let player: HTMLAudioElement
let load: ReturnType<typeof vi.fn<NarrationLoader>>
let play: ReturnType<typeof vi.spyOn>
const blob = () => new Blob(['generated-test-audio'], { type: 'audio/mpeg' })
async function action(fn: () => void) {
  await act(async () => {
    fn()
    await Promise.resolve()
  })
}
beforeEach(() => {
  vi.useFakeTimers()
  player = document.createElement('audio')
  vi.spyOn(window, 'Audio').mockImplementation(function () {
    return player
  })
  play = vi
    .spyOn(HTMLMediaElement.prototype, 'play')
    .mockImplementation(function (this: HTMLMediaElement) {
      if (this.src.startsWith('blob:')) this.dispatchEvent(new Event('playing'))
      return Promise.resolve()
    })
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.stubGlobal('matchMedia', () => ({
    matches: true,
    addEventListener() {},
    removeEventListener() {},
  }))
  URL.createObjectURL = vi.fn(() => 'blob:natural-voice')
  URL.revokeObjectURL = vi.fn()
  load = vi.fn<NarrationLoader>().mockResolvedValue(blob())
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function narration(agent: 'masculine' | 'feminine' = 'masculine', customer: 'masculine' | 'feminine' = 'feminine') {
  const { result, unmount } = renderHook(() => useTranscriptSpeech(turns, agent, customer, load))
  return {
    current: () => result.current,
    toggle: () => action(() => result.current.toggle(turns[0])),
    preview: (turn: TranscriptTurn, immediate = false) => action(() => result.current.preview(turn, immediate)),
    unmount,
  }
}

const tick = (ms: number) => action(() => vi.advanceTimersByTime(ms))
const emit = (type: string) => action(() => player.dispatchEvent(new Event(type)))

describe('natural hover narration', () => {
  it('keeps casting separate from identity facts', () => {
    expect(voiceAssignment('James', 'feminine')).toEqual({
      style: 'masculine',
      matched: true,
    })
    expect(voiceAssignment('Carol Jensen', 'masculine')).toEqual({
      style: 'feminine',
      matched: true,
    })
    expect(voiceAssignment('Alex', 'masculine').matched).toBe(false)
  })
  it('stays silent until enabled and uses exact masked text and role-specific mock voices', async () => {
    const voice = narration()
    await voice.preview(turns[0])
    await tick(500)
    expect(load).not.toHaveBeenCalled()
    await voice.toggle()
    expect(load.mock.calls[0].slice(0, 2)).toEqual([turns[0], 'af_heart'])
    expect(voice.current().speaking).toBe(1)
    await voice.preview(turns[2])
    await tick(299)
    expect(load).toHaveBeenCalledTimes(1)
    await tick(1)
    expect(load.mock.calls[1].slice(0, 2)).toEqual([turns[2], 'am_michael'])
    expect(voice.current().speaking).toBe(3)
    expect(window.Audio).toHaveBeenCalledTimes(1)
  })
  it('uses Bella and Fenrir for the other assigned role voices', async () => {
    const voice = narration('feminine', 'masculine')
    await voice.toggle()
    await voice.preview(turns[2], true)
    expect(load.mock.calls.map((call) => call[1])).toEqual([
      'am_fenrir',
      'af_bella',
    ])
  })
  it('does not restart delays, queue dialogue or replay finished passages on movement', async () => {
    const voice = narration()
    await voice.toggle()
    await voice.preview(turns[2])
    await tick(150)
    await voice.preview(turns[2])
    await tick(150)
    await emit('ended')
    const calls = play.mock.calls.length
    await voice.preview(turns[2])
    await tick(500)
    expect(load).toHaveBeenCalledTimes(2)
    expect(play).toHaveBeenCalledTimes(calls)
    expect(voice.current().speaking).toBeNull()
  })
  it('taps start pending previews immediately and repeat visits reuse only matching cached blobs', async () => {
    const voice = narration()
    await voice.toggle()
    await voice.preview(turns[2])
    await voice.preview(turns[2], true)
    expect(voice.current().speaking).toBe(3)
    await voice.preview(turns[0], true)
    expect(load).toHaveBeenCalledTimes(2)
    expect(voice.current().speaking).toBe(1)
    expect(URL.revokeObjectURL).toHaveBeenCalled()
  })
  it('stops on actions and never requests their audio', async () => {
    const voice = narration()
    await voice.toggle()
    await voice.preview(turns[1], true)
    expect(load).toHaveBeenCalledTimes(1)
    expect(voice.current().speaking).toBeNull()
  })
  it('rejects changed canonical text before requesting a clip', async () => {
    const voice = narration()
    await action(() =>
      voice.current().toggle({ ...turns[0], text: 'Invented wording' }),
    )
    expect(load).not.toHaveBeenCalled()
    expect(voice.current().error).toContain('unavailable for this passage')
  })
  it('aborts stale fetches and ignores late network results after switching turns', async () => {
    let resolve: (value: Blob) => void = () => {}
    load.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done
        }),
    )
    const voice = narration()
    await voice.toggle()
    const signal = load.mock.calls[0][2]
    await voice.preview(turns[2], true)
    expect(signal.aborted).toBe(true)
    const calls = play.mock.calls.length
    await action(() => resolve(blob()))
    expect(play).toHaveBeenCalledTimes(calls)
    expect(voice.current().speaking).toBe(3)
  })
  it('reports missing audio and invalid blobs with a retry state instead of another voice', async () => {
    load.mockRejectedValueOnce(new Error('Not prepared'))
    const voice = narration()
    await voice.toggle()
    expect(voice.current().enabled).toBe(false)
    expect(voice.current().error).toContain('Not prepared')
    load.mockResolvedValueOnce(new Blob(['not audio'], { type: 'text/plain' }))
    await voice.toggle()
    expect(voice.current().error).toContain('Invalid narration')
    await voice.toggle()
    expect(voice.current().error).toBe('')
    expect(voice.current().speaking).toBe(1)
  })
  it('does not report speaking during loading, buffering, pause or after completion', async () => {
    play.mockResolvedValue(undefined)
    const voice = narration()
    await voice.toggle()
    expect(voice.current().speaking).toBeNull()
    await emit('playing')
    expect(voice.current().speaking).toBe(1)
    await emit('waiting')
    expect(voice.current().speaking).toBeNull()
    await emit('playing')
    await emit('pause')
    expect(voice.current().speaking).toBeNull()
  })
  it('stops on Escape, window blur, hidden tabs, mute and unmount', async () => {
    const voice = narration()
    await voice.toggle()
    await action(() =>
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })),
    )
    expect(voice.current().speaking).toBeNull()
    await voice.preview(turns[0], true)
    await action(() => window.dispatchEvent(new Event('blur')))
    expect(voice.current().speaking).toBeNull()
    await voice.preview(turns[0], true)
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    await action(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(voice.current().speaking).toBeNull()
    await voice.toggle()
    expect(voice.current().enabled).toBe(false)
    await voice.toggle()
    await voice.preview(turns[2])
    const calls = load.mock.calls.length
    voice.unmount()
    await tick(500)
    expect(load).toHaveBeenCalledTimes(calls)
    expect(player.getAttribute('src')).toBeNull()
  })
  it('connects hover, focus, tap and leave without changing selection on hover', async () => {
    const select = vi.fn()
    render(
      <TranscriptWaveform
        turns={turns}
        agentName="James"
        selected={1}
        onSelect={select}
        onOpen={vi.fn()}
        loadNarration={load}
      />,
    )
    const short = screen.getByRole('button', { name: /View turn 3/ })
    await action(() =>
      fireEvent.click(
        screen.getByRole('button', { name: 'Enable demo voice' }),
      ),
    )
    await action(() => fireEvent.mouseMove(short))
    await tick(300)
    expect(load).toHaveBeenCalledTimes(2)
    expect(select).not.toHaveBeenCalled()
    fireEvent.mouseLeave(short)
    await action(() => fireEvent.click(short))
    expect(select).toHaveBeenLastCalledWith(3)
    expect(screen.queryByText('Voice settings')).toBeNull()
    expect(screen.getByRole('button', { name: 'Mute demo voice' })).toBeTruthy()
  })
})
