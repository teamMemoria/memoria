import { useState } from 'react'
import { Icon } from '../../components/Icon'
import { ApprovedReference } from '../../components/ApprovedReference'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '../../components/ui/sheet'
import { CheckEvidence } from './AssessmentElements'
import type { EvidenceHandler } from './assessment'
import type { CallReview, ScoringCheck } from '../../types/callReview'
import { canReadKnowledge } from '../../types/knowledge'

export type EvidenceSelection = {
  turns: number[]
  referenceId: string | null
  section: number | null
  full: boolean
  checkId?: string | null
}

export function EvidenceSheet({
  call,
  selection,
  referenceIds,
  checks,
  onSelect,
  open,
  onClose,
  onFullTranscript,
  restoreFocus,
}: {
  call: CallReview
  referenceIds: string[]
  checks: ScoringCheck[]
  onSelect: EvidenceHandler
  selection: EvidenceSelection
  open: boolean
  onClose: () => void
  onFullTranscript: () => void
  restoreFocus: () => void
}) {
  const check = checks.find((item) => item.id === selection.checkId)
  const [context, setContext] = useState(false)
  const transcript = call.transcript?.turns ?? []
  const selectedIndexes = transcript.flatMap((turn, index) =>
    selection.turns.includes(turn.number) ? [index] : [],
  )
  // Adjacent retained passages, not invented turn numbers when the source has gaps.
  const turns = transcript.filter(
    (turn, index) =>
      selection.full ||
      selection.turns.includes(turn.number) ||
      (context &&
        selectedIndexes.some((selected) => Math.abs(index - selected) === 1)),
  )
  const missing = selection.turns.filter(
    (number) => !transcript.some((turn) => turn.number === number),
  )
  const reference = call.references.find(
    (entry) =>
      entry.id === selection.referenceId &&
      referenceIds.includes(entry.id) &&
      canReadKnowledge(entry, call.agentId),
  )
  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <SheetContent
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          restoreFocus()
        }}
      >
        <SheetHeader>
          <p className="eyebrow">CONVERSATION {call.id}</p>
          <SheetTitle>
            {selection.full ? 'Full transcript' : 'Evidence'}
          </SheetTitle>
          <SheetDescription>
            Recorded conversation passages and applicable approved reference.
          </SheetDescription>
        </SheetHeader>
        <div className="sheet-body">
          {!selection.full && selection.turns.length > 0 && (
            <div className="evidence-toolbar">
              <span>
                {selection.turns.length} selected{' '}
                {selection.turns.length === 1 ? 'turn' : 'turns'}
              </span>
              <button
                className="context-toggle"
                aria-pressed={context}
                onClick={() => setContext(!context)}
              >
                <Icon name="conversations" size={16} />
                Surrounding turns
                <span className="switch-track">
                  <i />
                </span>
              </button>
            </div>
          )}
          {!call.transcript?.complete && (
            <p className="source-note">
              {call.transcript?.unavailableReason ||
                'The complete transcript is unavailable.'}{' '}
              Missing evidence does not establish an Agent error.
            </p>
          )}
          {missing.length > 0 && (
            <p className="source-note">
              Selected passages unavailable: {missing.join(', ')}.
            </p>
          )}
          <div className="evidence-thread">
            {turns.map((turn) => (
              <figure
                key={turn.number}
                className={`source-quote ${selection.turns.includes(turn.number) ? 'source-quote--selected' : 'source-quote--context'}`}
              >
                <figcaption>
                  <span
                    className={`speaker-avatar speaker-avatar--${turn.speaker.toLowerCase()}`}
                  >
                    {turn.speaker[0]}
                  </span>
                  <strong>{turn.speaker}</strong>
                  <span>
                    Turn {turn.number}
                    {turn.time ? ` · ${turn.time}` : ''}
                  </span>
                </figcaption>
                <blockquote>{turn.text}</blockquote>
                {selection.turns.includes(turn.number) && (
                  <span className="selected-source-label">
                    Selected passage
                  </span>
                )}
              </figure>
            ))}
          </div>
          {!turns.length && (
            <p className="source-note">
              No transcript passages available for this selection.
            </p>
          )}
          {call.requestLinks
            ?.filter((request) =>
              [...request.requestTurns, ...request.responseTurns].some(
                (number) => selection.turns.includes(number),
              ),
            )
            .map((request) => (
              <section key={request.id} className="source-reference">
                <h3>{request.text}</h3>
                <p>Recorded request state: {request.state}</p>
                {request.limitations.map((text) => (
                  <p key={text}>{text}</p>
                ))}
              </section>
            ))}
          {selection.checkId &&
            (check ? (
              <section className="selected-check">
                <CheckEvidence
                  key={check.id}
                  check={check}
                  onOpen={onSelect}
                  expanded
                />
              </section>
            ) : (
              <p>Selected check unavailable for this category.</p>
            ))}
          {selection.referenceId && (
            <section className="source-reference">
              <h3>Applicable reference</h3>
              {reference ? (
                <>
                  <h3>{reference.title}</h3>
                  <ApprovedReference
                    entry={reference}
                    highlightStep={selection.section}
                  />
                  {selection.section !== null &&
                    !reference.steps.some(
                      (step) => step.number === selection.section,
                    ) && <p>Selected reference section unavailable.</p>}
                </>
              ) : (
                <p>No approved reference available for this selection.</p>
              )}
            </section>
          )}
          <p className="source-note">
            <Icon name="info" />
            Agent statements do not verify system actions.
          </p>
        </div>
        <SheetFooter>
          {!selection.full && (
            <button
              className="button button--primary"
              onClick={onFullTranscript}
            >
              Full transcript
              <Icon name="arrowRight" />
            </button>
          )}
          <button className="button button--secondary" onClick={onClose}>
            Back to assessment
          </button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
