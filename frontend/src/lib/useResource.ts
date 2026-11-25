import { useEffect, useState } from 'react'

export type Resource<T> =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'unavailable' }
  | { status: 'ready'; data: T }

export function useResource<T>(read: (() => Promise<T | null>) | null) {
  const [request, setRequest] = useState<{
    read: typeof read
    result: Resource<T>
  }>()
  const [attempt, setAttempt] = useState(0)
  const state: Resource<T> = !read
    ? { status: 'unavailable' }
    : request?.read === read
      ? request.result
      : { status: 'loading' }

  useEffect(() => {
    if (!read) return
    let active = true
    void read().then(
      (data) => {
        if (!active) return
        const result = data === null
          ? { status: 'unavailable' } as const
          : { status: 'ready', data } as const
        setRequest({ read, result })
      },
      () => {
        if (active) setRequest({ read, result: { status: 'error' } })
      },
    )
    return () => {
      active = false
    }
  }, [read, attempt])

  function retry() {
    setRequest(undefined)
    setAttempt((value) => value + 1)
  }

  function update(change: (value: T) => T) {
    setRequest((current) =>
      current?.read === read && current.result.status === 'ready'
        ? { read, result: { status: 'ready', data: change(current.result.data) } }
        : current,
    )
  }

  return { ...state, retry, update }
}
