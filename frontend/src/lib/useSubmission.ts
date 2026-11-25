import { useRef, useState } from 'react'

export function useSubmission<Action = true>() {
  const inFlight = useRef(false)
  const [saving, setSaving] = useState<Action | null>(null)
  const [failed, setFailed] = useState<Action | null>(null)

  async function submit(action: Action, save: () => Promise<void>) {
    if (inFlight.current) return
    inFlight.current = true
    setSaving(action)
    setFailed(null)
    try {
      await save()
    } catch {
      setFailed(action)
    } finally {
      inFlight.current = false
      setSaving(null)
    }
  }

  return { submit, saving, failed }
}
