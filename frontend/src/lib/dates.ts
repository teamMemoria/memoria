const calendar = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeZone: 'UTC' })
const clock = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' })

export function formatDate(value: string | null, fallback = 'Not supplied') {
  const date = value ? new Date(`${value.slice(0, 10)}T00:00:00Z`) : null
  return date && Number.isFinite(date.valueOf()) ? calendar.format(date) : fallback
}

export function formatTimestamp(value: string) {
  return `${clock.format(new Date(value))} UTC`
}
