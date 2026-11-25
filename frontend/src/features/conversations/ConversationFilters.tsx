import { Button, Panel, TextField } from '../../components/controls'
import { MemoriaSelectField } from '../../components/ui/select'
import { scoreOptions } from './scoreBands'

export function ConversationFilters({ team, simulation, query, value, statusOptions, disabled, onSearch, onSelect }: {
  team?: boolean
  simulation: boolean
  query: string
  value: string
  statusOptions: readonly (readonly [string, string])[]
  disabled: boolean
  onSearch: (query: string) => void
  onSelect: (value: string) => void
}) {
  const prefix = team ? 'review-queue' : 'conversation'
  const searchLabel = team ? 'Search team calls' : 'Search calls'
  return (
    <div className="conversation-filters" role="search" aria-label={team ? 'Find team conversations' : 'Find conversations'}>
      <TextField
        id={`${prefix}-search`}
        label={searchLabel}
        hideLabel
        type="search"
        placeholder={simulation ? 'Search by call, agent or topic' : team ? 'Search by call, agent, topic or reason' : searchLabel}
        value={query}
        onChange={(event) => onSearch(event.target.value)}
        disabled={disabled}
      />
      <MemoriaSelectField
        key={simulation ? 'score' : 'status'}
        id={`${prefix}-${simulation ? 'score' : 'status'}`}
        label={simulation ? 'Overall score' : 'Review status'}
        value={value}
        onValueChange={onSelect}
        disabled={disabled}
        options={simulation ? scoreOptions : statusOptions}
      />
    </div>
  )
}

export function NoMatchingConversations({ scored, onClear }: { scored: boolean; onClear: () => void }) {
  return (
    <Panel title="No matching conversations">
      <p>{scored ? 'Try another search or score range.' : 'Try another search or review status.'}</p>
      <Button variant="secondary" onClick={onClear}>Clear filters</Button>
    </Panel>
  )
}
