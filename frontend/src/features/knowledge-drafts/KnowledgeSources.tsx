import { Fragment, useRef } from 'react'
import { Icon } from '../../components/Icon'
import { Button, Panel } from '../../components/controls'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '../../components/ui/dialog'
import type { ConversationPassage, KnowledgeDraft } from '../../types/knowledge'
import { draftPresentation } from './draftPresentation'
import { queueTabFor, queueTabs } from './draftsQueue'

export function KnowledgeSources({ entry }: { entry: KnowledgeDraft }) {
  const sourceIds = entry.sourceConversationIds
  const count = sourceIds.length
  const height = 100 * count
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
      <div className="knowledge-flow" data-dense-sources={count > 5 || undefined}>
        <div className="knowledge-source-map">
          <div className="knowledge-source-list">
            {sourceIds.map((id) => (
              <SourceCall key={id} id={id}
                passages={entry.passages.filter((passage) => passage.conversationId === id)}
              />
            ))}
            {!count && <p>No source conversations are available.</p>}
          </div>
          {count > 0 && (
            <div className="knowledge-source-lines" aria-hidden="true">
              <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none">
                {sourceIds.map((id, index) => {
                  const y = 100 * index + 50
                  return <path key={id} d={`M 0 ${y} C 48 ${y}, 52 ${height / 2}, 100 ${height / 2}`} />
                })}
              </svg>
            </div>
          )}
        </div>
        {count > 0 && <span className="knowledge-source-mobile-arrow" aria-hidden="true"><Icon name="arrowRight" /></span>}
        <div className="knowledge-flow-stages">
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
      </div>
    </Panel>
  )
}

function SourceCall({ id, passages }: { id: string; passages: ConversationPassage[] }) {
  const titleRef = useRef<HTMLHeadingElement>(null)
  const sourceKey = passages.find((passage) => /^ABCD:\d+$/.test(passage.sourceKey ?? ''))?.sourceKey
  const label = sourceKey?.replace(':', ' ') ?? `Call ${id}`
  const count = passages.length
  const caption = count ? `${count} cited ${count === 1 ? 'passage' : 'passages'}` : 'Passage not supplied'
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button className="knowledge-source flex-center" type="button" aria-label={`View source call ${sourceKey ? label : id}`}>
          <Icon name="conversations" size={20} />
          <span><strong>{label}</strong><span>{caption}</span></span>
        </button>
      </DialogTrigger>
      <DialogContent className="knowledge-source-dialog" overlayClassName="knowledge-source-backdrop"
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          titleRef.current?.focus()
        }}
      >
        <header className="knowledge-source-dialog-header">
          <p>Source conversation</p>
          <DialogTitle ref={titleRef} tabIndex={-1}>{label}</DialogTitle>
        </header>
        <div className="knowledge-source-dialog-body">
          {count > 0 && <h3>{caption}</h3>}
          <SourcePassages passages={passages} />
          <DialogDescription className="knowledge-source-note">
            <Icon name="info" />
            <span>Conversation evidence shows where the draft came from. Policy verification requires an authoritative reference.</span>
          </DialogDescription>
        </div>
        <footer className="knowledge-source-dialog-footer">
          <DialogClose asChild><Button variant="secondary">Back to draft</Button></DialogClose>
        </footer>
      </DialogContent>
    </Dialog>
  )
}

function SourcePassages({ passages }: { passages: ConversationPassage[] }) {
  return passages.length ? (
    <ul className="knowledge-review-passages">
      {passages.map((passage) => (
        <li key={`${passage.turnNumber}-${passage.speaker}`} data-speaker={passage.speaker}>
          <span className="knowledge-passage-meta">
            <strong>{passage.speaker}</strong>
            <span>Turn {passage.turnNumber}</span>
          </span>
          <blockquote>{passage.text}</blockquote>
        </li>
      ))}
    </ul>
  ) : (
    <p>No conversation passages are available for this source.</p>
  )
}
