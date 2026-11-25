import { createHash } from 'node:crypto'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { TranscriptTurn } from '../src/types/callReview.js'

const voices = {
  Agent: ['am_michael', 'af_bella'],
  Customer: ['am_fenrir', 'af_heart'],
}

function hash(value: string | Buffer) {
  return createHash('sha256').update(value).digest('hex')
}

export function simulationNarration(directory: string) {
  const clips = new Map<string, { file: string; digest: string }>()
  for (const file of existsSync(directory) ? readdirSync(directory) : []) {
    if (!/^[a-f0-9]{64}\.json$/.test(file)) continue
    try {
      const { identity, sha256, synthetic } = JSON.parse(readFileSync(join(directory, file), 'utf8'))
      if (synthetic !== true || !/^[a-f0-9]{64}$/.test(sha256) || typeof identity.text !== 'string') continue
      const key = `${identity.speaker}/${identity.voice}/${hash(identity.text)}`
      clips.set(key, { file: join(directory, file.replace(/\.json$/, '.mp3')), digest: sha256 })
    } catch {
      // Incomplete or invalid cache entries are unavailable.
    }
  }

  return async (turn: TranscriptTurn | undefined, params: URLSearchParams) => {
    const voice = params.get('voice') ?? ''
    if (!turn || turn.speaker === 'System action' || !turn.text.trim()) return { status: 404 }
    if (!voices[turn.speaker].includes(voice)) return { status: 400 }
    const digest = hash(turn.text)
    if (digest !== params.get('text_sha256')) return { status: 409 }
    const clip = clips.get(`${turn.speaker}/${voice}/${digest}`)
    if (!clip) return { status: 503 }
    const audio = await readFile(clip.file).catch(() => null)
    if (!audio?.length || hash(audio) !== clip.digest) return { status: 503 }
    return { status: 200, audio }
  }
}
