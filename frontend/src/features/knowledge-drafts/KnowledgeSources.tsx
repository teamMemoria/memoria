import { Icon } from '../../components/Icon'
import { Panel } from '../../components/controls'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '../../components/ui/dialog'
import type { KnowledgeDraft } from '../../types/knowledge'
import { queueTabFor, queueTabs } from './draftsQueue'

export function KnowledgeSources({ entry }: { entry: KnowledgeDraft }) {
  const height = Math.max(88, entry.sourceConversationIds.length * 96 - 8)

  return (
    <Panel title="Sources" className="knowledge-sources">
      <p className="metadata-line">
        Found in {entry.sourceConversationIds.length}{' '}
        {entry.sourceConversationIds.length === 1
          ? 'conversation'
          : 'conversations'}
        . Source calls show examples; they do not verify the policy.
      </p>
      <div className="knowledge-flow">
        <div className="knowledge-source-list">
          {entry.sourceConversationIds.map((id) => {
            const passages = entry.passages.filter(
              (passage) => passage.conversationId === id,
            )
            return (
              <Dialog key={id}>
                <DialogTrigger asChild>
                  <button
                    className="knowledge-source"
                    type="button"
                    aria-label={`View source call ${id}`}
                  >
                    <Icon name="conversations" size={24} />
                    <span>
                      <strong>{id}</strong>
                      <span>Source conversation</span>
                      <span>
                        {passages.length
                          ? `${passages.length} cited ${passages.length === 1 ? 'passage' : 'passages'}`
                          : 'Passage not supplied'}
                      </span>
                    </span>
                  </button>
                </DialogTrigger>
                <DialogContent>
                  <DialogTitle>Call {id}</DialogTitle>
                  <DialogDescription>
                    Conversation evidence shows where the draft came from. It
                    does not establish policy authority.
                  </DialogDescription>
                  {passages.length ? (
                    <ul className="knowledge-review-passages">
                      {passages.map((passage) => (
                        <li key={`${passage.turnNumber}-${passage.speaker}`}>
                          <span className="metadata-line">
                            <span>Turn {passage.turnNumber}</span>
                            <span>{passage.speaker}</span>
                          </span>
                          <blockquote>{passage.text}</blockquote>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>
                      No conversation passages are available for this source.
                    </p>
                  )}
                </DialogContent>
              </Dialog>
            )
          })}
          {!entry.sourceConversationIds.length && (
            <p>No source conversations are available.</p>
          )}
        </div>
        <svg
          className="knowledge-source-connectors"
          viewBox={`0 0 128 ${height}`}
          aria-hidden="true"
          preserveAspectRatio="none"
        >
          {entry.sourceConversationIds.map((id, index) => {
            const path = `M 0 ${44 + index * 96} C 64 ${44 + index * 96}, 64 ${height / 2}, 128 ${height / 2}`
            return (
              <g key={id}>
                <path d={path} />
                <path
                  className="knowledge-source-flow"
                  d={path}
                  pathLength={100}
                />
              </g>
            )
          })}
        </svg>
        <div className="knowledge-flow-node knowledge-flow-node--draft">
          <Icon name="document" size={24} />
          <span>
            <strong>Draft</strong>
            <span>{entry.title}</span>
          </span>
        </div>
        <span className="knowledge-flow-arrow" aria-hidden="true">
          <Icon name="arrowRight" />
        </span>
        <div className="knowledge-flow-node knowledge-flow-node--review">
          <Icon name="account" size={24} />
          <span>
            <strong>Manager review</strong>
            <span>{queueTabs[queueTabFor(entry)]}</span>
          </span>
        </div>
        <span className="knowledge-flow-arrow" aria-hidden="true">
          <Icon name="arrowRight" />
        </span>
        <div
          className={`knowledge-flow-node knowledge-flow-node--${entry.status === 'approved' ? 'approved' : 'locked'}`}
        >
          <Icon
            name={entry.status === 'approved' ? 'check' : 'lock'}
            size={24}
          />
          <span>
            <strong>Approved knowledge</strong>
            <span>
              {entry.status === 'approved'
                ? 'Available to assigned Agents'
                : 'Locked'}
            </span>
          </span>
        </div>
      </div>
    </Panel>
  )
}
