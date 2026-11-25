import type { ReactNode } from 'react'
import './workspace-table.css'

type Column = {
  label: string
  width: number
  sort?: 'descending' | 'ascending'
  hideLabel?: boolean
}

export function WorkspaceTable({ label, caption, columns, children }: {
  label: string
  caption: string
  columns: readonly Column[]
  children: ReactNode
}) {
  return (
    <div className="conversation-table-scroll" role="region" aria-label={label} tabIndex={0}>
      <table className="conversation-table workspace-table">
        <caption className="workspace-table-sr-only">{caption}</caption>
        <colgroup>
          {columns.map(({ label, width }) => <col key={label} style={{ width: `${width}%` }} />)}
        </colgroup>
        <thead>
          <tr>
            {columns.map(({ label, sort, hideLabel }) => (
              <th key={label} scope="col" aria-sort={sort}>
                {hideLabel ? <span className="workspace-table-sr-only">{label}</span> : label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}
