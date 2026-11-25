import { Fragment } from 'react'
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
import { draftPresentation } from './draftPresentation'
import { queueTabFor, queueTabs } from './draftsQueue'

export function KnowledgeSources({ entry }: { entry: KnowledgeDraft }) {
  const height = Math.max(88, entry.sourceConversationIds.length * 96 - 8)
  const published = entry.status === 'approved'
  const stages = [
    { stage: 'draft', icon: 'document', heading: 'Draft', detail: draftPresentation(entry.title, entry.layer).title },
    { stage: 'review', icon: 'account', heading: 'Manager review', detail: queueTabs[queueTabFor(entry)] },
    {
      stage: published ? 'approved' : 'locked',
      icon: published ? 'check' : 'lock',
      heading: 'Approved knowledge',
      detail: published ? 'Available to assigned Agents' : 'Locked',
    },
  ] as const

  return (
    <Panel title="Sources" className="knowledge-sources">
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
                    className="knowledge-source flex-center"
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
        {stages.map(({ stage, icon, heading, detail }, index) => (
          <Fragment key={stage}>
            {index > 0 && (
              <span className="knowledge-flow-arrow" aria-hidden="true">
                <Icon name="arrowRight" />
              </span>
            )}
            <div className={`knowledge-flow-node flex-center knowledge-flow-node--${stage}`}>
              <Icon name={icon} size={24} />
              <span>
                <strong>{heading}</strong>
                <span>{detail}</span>
              </span>
            </div>
          </Fragment>
        ))}
      </div>
    </Panel>
  )
}
