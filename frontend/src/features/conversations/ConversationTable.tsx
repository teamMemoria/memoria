import type { ComponentProps, ReactNode } from 'react'
import { Link } from 'react-router'
import { WorkspaceTable } from '../../components/WorkspaceTable'
import { percentage } from '../../types/callReview'
import type { Conversation } from './conversations'
import { scoreColumns } from './scoreBands'

export function ConversationTable<Row extends Conversation>({
  rows, label, caption, columns, scored, link, details,
}: Pick<ComponentProps<typeof WorkspaceTable>, 'label' | 'caption' | 'columns'> & {
  rows: Row[]
  scored: boolean
  link: (row: Row) => Pick<ComponentProps<typeof Link>, 'to' | 'aria-label' | 'className'>
  details: (row: Row) => ReactNode
}) {
  return (
    <>
      <p className="sr-only" role="status">
        {rows.length} {rows.length === 1 ? 'conversation' : 'conversations'} shown
      </p>
      <WorkspaceTable label={label} caption={caption} columns={scored ? scoreColumns : columns}>
        {rows.map((row) => (
          <tr key={row.id}>
            <td><Link {...link(row)}>{row.sourceId ? `ABCD ${row.sourceId}` : row.id}</Link></td>
            {scored ? (
              <>
                <td>{row.agentName}</td>
                <td>{row.topic}</td>
                <td>{percentage(row.simulationScore)}</td>
              </>
            ) : details(row)}
          </tr>
        ))}
      </WorkspaceTable>
    </>
  )
}
