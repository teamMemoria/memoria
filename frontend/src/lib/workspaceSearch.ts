import { useSearchParams } from 'react-router'

export function withQuery(params: URLSearchParams, changes: Record<string, string | null>) {
  const next = new URLSearchParams(params)
  for (const [key, value] of Object.entries(changes)) {
    if (value === null) next.delete(key)
    else next.set(key, value)
  }
  return next
}

export function conversationFilters(params: URLSearchParams, keepEmpty = true) {
  const next = new URLSearchParams()
  for (const key of ['q', 'status']) {
    const value = params.get(key)
    if (value !== null && (keepEmpty || value)) next.set(key, value)
  }
  return next
}

export function useWorkspaceSearch(defaults: Record<string, string> = {}) {
  const [params, setParams] = useSearchParams()
  function filter(key: string, value: string, replace = true) {
    const next = !value || value === defaults[key] ? null : value
    setParams((previous) => withQuery(previous, { [key]: next }), { replace })
  }
  return { params, filter, setParams, query: params.get('q') ?? '', search: params.size ? `?${params}` : '' }
}
