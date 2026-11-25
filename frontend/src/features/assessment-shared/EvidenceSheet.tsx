import { transcriptEvidence } from '../../lib/transcriptEvidence'
import { TranscriptNotice } from '../../components/TranscriptNotice'
import { useState } from 'react'
import { Icon } from '../../components/Icon'
import { ApprovedReference } from '../../components/ApprovedReference'
import * as Sheet from '@radix-ui/react-dialog'
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
  const { turns, missing, selected } = transcriptEvidence(
    call.transcript, selection.turns,
    selection.full ? 'full' : context ? 'surrounding' : 'selected',
  )
  const reference = call.references.find(
    (entry) =>
      entry.id === selection.referenceId &&
      referenceIds.includes(entry.id) &&
      canReadKnowledge(entry, call.agentId),
  )
  return (
    <Sheet.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <Sheet.Portal>
        <Sheet.Overlay data-slot="sheet-overlay" />
        <Sheet.Content
          data-slot="sheet-content"
          className="evidence-sheet"
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            restoreFocus()
          }}
        >
          <div data-slot="sheet-header">
            <p className="eyebrow">CONVERSATION {call.id}</p>
            <Sheet.Title data-slot="sheet-title">
              {selection.full ? 'Full transcript' : 'Evidence'}
            </Sheet.Title>
            <Sheet.Description data-slot="sheet-description">
              {call.assessmentSource === 'simulation'
                ? 'Archived ABCD passages and assessment sources.'
                : 'Recorded conversation passages and applicable approved reference.'}
            </Sheet.Description>
          </div>
          <div className="sheet-body">
            {!selection.full && selection.turns.length > 0 && (
              <div className="evidence-toolbar flex-center">
                <span>
                  {selection.turns.length} selected{' '}
                  {selection.turns.length === 1 ? 'turn' : 'turns'}
                </span>
                <button
                  className="context-toggle inline-center"
                  aria-pressed={context}
                  onClick={() => setContext(!context)}
                >
                  <Icon name="conversations" size={16} />
                  Surrounding turns
                  <span className="switch-track flex-center">
                    <i />
                  </span>
                </button>
              </div>
            )}
            <TranscriptNotice transcript={call.transcript} className="source-note" />
            {missing.length > 0 && (
              <p className="source-note">
                Selected passages unavailable: {missing.join(', ')}.
              </p>
            )}
            <div className="evidence-thread">
              {turns.map((turn) => (
                <figure
                  key={turn.number}
                  className={`source-quote ${selected.has(turn.number) ? 'source-quote--selected' : 'source-quote--context'}`}
                >
                  <figcaption>
                    <span
                      className={`speaker-avatar grid-center speaker-avatar--${turn.speaker.toLowerCase()}`}
                    >
                      {turn.speaker[0]}
                    </span>
                    <strong>{turn.speaker}</strong>
                    <span>
                      Turn {turn.number}
                      {turn.time ? ` (${turn.time})` : ''}
                    </span>
                  </figcaption>
                  <blockquote>{turn.text}</blockquote>
                  {selected.has(turn.number) && (
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
                  (number) => selected.has(number),
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
          <div data-slot="sheet-footer">
            {!selection.full && (
              <button
                className="button button--primary"
                onClick={onFullTranscript}
              >
                Full transcript
              </button>
            )}
            <button className="button button--secondary" onClick={onClose}>
              Back to assessment
            </button>
          </div>
          <Sheet.Close data-slot="sheet-close" className="close-dialog grid-center" aria-label="Close evidence">×</Sheet.Close>
        </Sheet.Content>
      </Sheet.Portal>
    </Sheet.Root>
  )
}
