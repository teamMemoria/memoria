import { useEffect, useRef, useState } from 'react'
import type { TranscriptTurn } from '../../types/callReview'

// A cumulative count of supplied records, not a performance score or inferred event log.
export function ConversationChart({
  turns,
  events,
  label,
  colour,
  selected,
  onSelect,
}: {
  turns: TranscriptTurn[]
  events: number[]
  label: string
  colour: string
  selected?: number
  onSelect: (turn: number) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const [plotWidth, setPlotWidth] = useState(1000)
  useEffect(() => {
    const element = container.current!
    const measure = () => setPlotWidth(Math.max(200, element.clientWidth))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const [hover, setHover] = useState<number | null>(null)
  const points = turns.filter((turn) => events.includes(turn.number))
  const total = points.reduce(
    (sum, turn) =>
      sum + events.filter((number) => number === turn.number).length,
    0,
  )
  const end = Math.max(1, turns.length - 1)
  const height = 190,
    left = 38,
    width = plotWidth - 76,
    bottom = 220
  const position = (number: number) =>
    left + (turns.findIndex((turn) => turn.number === number) / end) * width
  const data = points.map((turn, index) => {
    const count = points
      .slice(0, index + 1)
      .reduce(
        (sum, point) =>
          sum + events.filter((number) => number === point.number).length,
        0,
      )
    return {
      turn,
      count,
      x: position(turn.number),
      y: bottom - (count / Math.max(total, 1)) * height,
    }
  })
  // Step changes are justified by retained source positions; no interpolated times or outcomes.
  const path = `M${left},${bottom} ${data.map((p) => `H${p.x} V${p.y}`).join(' ')} H${left + width}`
  const tickCount = Math.min(
    turns.length,
    Math.max(2, Math.floor(plotWidth / 150)),
  )
  const ticks = Array.from(
    { length: tickCount },
    (_, index) =>
      turns[
        Math.round((index * (turns.length - 1)) / Math.max(1, tickCount - 1))
      ],
  )
  const active = data.find((point) => point.turn.number === hover)
  return (
    <div ref={container} className="conversation-graph source-chart">
      <div className="chart-axis-label">{label} · retained turn order</div>
      {points.length ? (
        <>
          <svg
            viewBox={`0 0 ${plotWidth} 260`}
            role="group"
            aria-label={`${label} by retained turn order`}
          >
            {[0, total / 2, total]
              .filter(
                (value, index, all) =>
                  Number.isInteger(value) && all.indexOf(value) === index,
              )
              .map((value) => {
                const y = bottom - (value / total) * height
                return (
                  <g key={value}>
                    <line
                      x1={left}
                      x2={left + width}
                      y1={y}
                      y2={y}
                      stroke="#edf0f5"
                    />
                    <text x={left - 14} y={y + 4} textAnchor="end">
                      {value}
                    </text>
                  </g>
                )
              })}
            <path d={`${path} V${bottom} Z`} fill={colour} opacity=".4" />
            <path d={path} stroke={colour} fill="none" strokeWidth="1.5" />
            {data.map((point) => (
              <g
                key={point.turn.number}
                tabIndex={0}
                role="button"
                aria-label={`Chart point: turn ${point.turn.number}, ${point.count} recorded`}
                onMouseEnter={() => setHover(point.turn.number)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(point.turn.number)}
                onBlur={() => setHover(null)}
                onClick={() => onSelect(point.turn.number)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onSelect(point.turn.number)
                  }
                }}
              >
                <circle cx={point.x} cy={point.y} r="14" fill="transparent" />
                <circle
                  cx={point.x}
                  cy={point.y}
                  r={selected === point.turn.number ? 5 : 3.5}
                  fill={colour}
                  stroke="white"
                  strokeWidth="2"
                />
              </g>
            ))}
            {ticks.map((turn) => {
              return (
                <text
                  key={turn.number}
                  x={position(turn.number)}
                  y="248"
                  textAnchor="middle"
                >
                  Turn {turn.number}
                </text>
              )
            })}
          </svg>
          {active && (
            <div
              className="graph-tooltip"
              role="status"
              style={{
                left: `${Math.min(80, Math.max(20, (active.x / plotWidth) * 100))}%`,
                top: Math.max(36, active.y - 45),
              }}
            >
              <small>Turn {active.turn.number}</small>
              <strong>{active.count} recorded</strong>
              <span>{active.turn.speaker}</span>
            </div>
          )}
        </>
      ) : (
        <div className="source-chart-empty">
          No supported records supplied for this chart.
        </div>
      )}
    </div>
  )
}
