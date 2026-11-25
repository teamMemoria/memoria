import { StatusLabel } from './controls'
import type { CSSProperties } from 'react'
import './count-bar.css'

type Segment<Value extends string> = {
  value: Value
  label: string
  count: number
  tone: 'positive' | 'attention' | 'neutral' | 'negative'
}

export function CountBar<Value extends string>({ label, segments, selected, onPreview, onSelect }: {
  label: string
  segments: readonly Segment<Value>[]
  selected: Value | null
  onPreview: (value: Value | null) => void
  onSelect: (value: Value) => void
}) {
  const visible = segments.filter(({ count }) => count > 0)
  if (!visible.length) return null
  const columns = visible.map(({ count }) => `minmax(0, ${count}fr)`).join(' ')

  return (
    <figure className="count-bar" aria-label={label} style={{ '--count-bar-columns': columns } as CSSProperties}>
      <div className="count-bar-track" onPointerLeave={() => onPreview(null)}>
        {visible.map(({ value, label, count, tone }) => (
          <button
            key={value}
            type="button"
            className={`count-bar-segment count-bar-fill--${tone}`}
            aria-label={`${label} (${count})`}
            aria-pressed={selected === value}
            onPointerEnter={(event) => {
              if (event.pointerType === 'mouse') onPreview(value)
            }}
            onClick={() => onSelect(value)}
          />
        ))}
      </div>
      <figcaption className="count-bar-legend" aria-hidden="true">
        {visible.map(({ value, label, count, tone }) => (
          <StatusLabel key={value} tone={tone}><span>{label} ({count})</span></StatusLabel>
        ))}
      </figcaption>
    </figure>
  )
}
