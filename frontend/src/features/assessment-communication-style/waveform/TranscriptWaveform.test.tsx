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
    const { result } = renderHook(() =>
      useTranscriptSpeech(turns, 'masculine', 'feminine', load),
    )
    await action(() => {
      result.current.preview(turns[0])
      vi.advanceTimersByTime(500)
    })
    expect(load).not.toHaveBeenCalled()
    await action(() => result.current.toggle(turns[0]))
    expect(load.mock.calls[0].slice(0, 2)).toEqual([turns[0], 'af_heart'])
    expect(result.current.speaking).toBe(1)
    await action(() => result.current.preview(turns[2]))
    await action(() => vi.advanceTimersByTime(299))
    expect(load).toHaveBeenCalledTimes(1)
    await action(() => vi.advanceTimersByTime(1))
    expect(load.mock.calls[1].slice(0, 2)).toEqual([turns[2], 'am_michael'])
    expect(result.current.speaking).toBe(3)
    expect(window.Audio).toHaveBeenCalledTimes(1)
  })
  it('uses Bella and Fenrir for the other assigned role voices', async () => {
    const { result } = renderHook(() =>
      useTranscriptSpeech(turns, 'feminine', 'masculine', load),
    )
    await action(() => result.current.toggle(turns[0]))
    await action(() => result.current.preview(turns[2], true))
    expect(load.mock.calls.map((call) => call[1])).toEqual([
      'am_fenrir',
      'af_bella',
    ])
  })
  it('does not restart delays, queue dialogue or replay finished passages on movement', async () => {
    const { result } = renderHook(() =>
      useTranscriptSpeech(turns, 'masculine', 'feminine', load),
    )
    await action(() => result.current.toggle(turns[0]))
    await action(() => result.current.preview(turns[2]))
    await action(() => vi.advanceTimersByTime(150))
    await action(() => result.current.preview(turns[2]))
    await action(() => vi.advanceTimersByTime(150))
    await action(() => player.dispatchEvent(new Event('ended')))
    const calls = play.mock.calls.length
    await action(() => {
      result.current.preview(turns[2])
      vi.advanceTimersByTime(500)
    })
    expect(load).toHaveBeenCalledTimes(2)
    expect(play).toHaveBeenCalledTimes(calls)
    expect(result.current.speaking).toBeNull()
  })
  it('taps start pending previews immediately and repeat visits reuse only matching cached blobs', async () => {
    const { result } = renderHook(() =>
      useTranscriptSpeech(turns, 'masculine', 'feminine', load),
    )
    await action(() => result.current.toggle(turns[0]))
    await action(() => result.current.preview(turns[2]))
    await action(() => result.current.preview(turns[2], true))
    expect(result.current.speaking).toBe(3)
    await action(() => result.current.preview(turns[0], true))
    expect(load).toHaveBeenCalledTimes(2)
    expect(result.current.speaking).toBe(1)
    expect(URL.revokeObjectURL).toHaveBeenCalled()
  })
  it('stops on actions and never requests their audio', async () => {
    const { result } = renderHook(() =>
      useTranscriptSpeech(turns, 'masculine', 'feminine', load),
    )
    await action(() => result.current.toggle(turns[0]))
    await action(() => result.current.preview(turns[1], true))
    expect(load).toHaveBeenCalledTimes(1)
    expect(result.current.speaking).toBeNull()
  })
  it('rejects changed canonical text before requesting a clip', async () => {
    const { result } = renderHook(() =>
      useTranscriptSpeech(turns, 'masculine', 'feminine', load),
    )
    await action(() =>
      result.current.toggle({ ...turns[0], text: 'Invented wording' }),
    )
    expect(load).not.toHaveBeenCalled()
    expect(result.current.error).toContain('unavailable for this passage')
  })
  it('aborts stale fetches and ignores late network results after switching turns', async () => {
    let resolve: (value: Blob) => void = () => {}
    load.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done
        }),
    )
    const { result } = renderHook(() =>
      useTranscriptSpeech(turns, 'masculine', 'feminine', load),
    )
    await action(() => result.current.toggle(turns[0]))
    const signal = load.mock.calls[0][2]
    await action(() => result.current.preview(turns[2], true))
    expect(signal.aborted).toBe(true)
    const calls = play.mock.calls.length
    await action(() => resolve(blob()))
    expect(play).toHaveBeenCalledTimes(calls)
    expect(result.current.speaking).toBe(3)
  })
  it('reports missing audio and invalid blobs with a retry state instead of another voice', async () => {
    load.mockRejectedValueOnce(new Error('Not prepared'))
    const { result } = renderHook(() =>
      useTranscriptSpeech(turns, 'masculine', 'feminine', load),
    )
    await action(() => result.current.toggle(turns[0]))
    expect(result.current.enabled).toBe(false)
    expect(result.current.error).toContain('Not prepared')
    load.mockResolvedValueOnce(new Blob(['not audio'], { type: 'text/plain' }))
    await action(() => result.current.toggle(turns[0]))
    expect(result.current.error).toContain('Invalid narration')
    await action(() => result.current.toggle(turns[0]))
    expect(result.current.error).toBe('')
    expect(result.current.speaking).toBe(1)
  })
  it('does not report speaking during loading, buffering, pause or after completion', async () => {
    play.mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      useTranscriptSpeech(turns, 'masculine', 'feminine', load),
    )
    await action(() => result.current.toggle(turns[0]))
    expect(result.current.speaking).toBeNull()
    await action(() => player.dispatchEvent(new Event('playing')))
    expect(result.current.speaking).toBe(1)
    await action(() => player.dispatchEvent(new Event('waiting')))
    expect(result.current.speaking).toBeNull()
    await action(() => player.dispatchEvent(new Event('playing')))
    await action(() => player.dispatchEvent(new Event('pause')))
    expect(result.current.speaking).toBeNull()
  })
  it('stops on Escape, window blur, hidden tabs, mute and unmount', async () => {
    const { result, unmount } = renderHook(() =>
      useTranscriptSpeech(turns, 'masculine', 'feminine', load),
    )
    await action(() => result.current.toggle(turns[0]))
    await action(() =>
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })),
    )
    expect(result.current.speaking).toBeNull()
    await action(() => result.current.preview(turns[0], true))
    await action(() => window.dispatchEvent(new Event('blur')))
    expect(result.current.speaking).toBeNull()
    await action(() => result.current.preview(turns[0], true))
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    await action(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(result.current.speaking).toBeNull()
    await action(() => result.current.toggle(turns[0]))
    expect(result.current.enabled).toBe(false)
    await action(() => result.current.toggle(turns[0]))
    await action(() => result.current.preview(turns[2]))
    const calls = load.mock.calls.length
    unmount()
    await action(() => vi.advanceTimersByTime(500))
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
    await action(() => vi.advanceTimersByTime(300))
    expect(load).toHaveBeenCalledTimes(2)
    expect(select).not.toHaveBeenCalled()
    fireEvent.mouseLeave(short)
    await action(() => fireEvent.click(short))
    expect(select).toHaveBeenLastCalledWith(3)
    expect(screen.queryByText('Voice settings')).toBeNull()
    expect(screen.getByRole('button', { name: 'Mute demo voice' })).toBeTruthy()
  })
})
