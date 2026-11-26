import { transcriptEvidence } from '../../lib/transcriptEvidence'
import { TranscriptNotice } from '../../components/TranscriptNotice'
import { useRef, useState } from 'react'
import { Icon } from '../../components/Icon'
import { ApprovedReference } from '../../components/ApprovedReference'
import { Button } from '../../components/controls'
import * as Sheet from '@radix-ui/react-dialog'
import { CheckEvidenceSummary } from './CheckEvidenceSummary'
import { checkTitle, checkTurns } from './assessment'
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
  categoryTitle,
  selection,
  referenceIds,
  checks,
  onSelectTurn,
  open,
  onClose,
  onFullTranscript,
  restoreFocus,
}: {
  call: CallReview
  categoryTitle: string
  referenceIds: string[]
  checks: ScoringCheck[]
  onSelectTurn: (number: number) => void
  selection: EvidenceSelection
  open: boolean
  onClose: () => void
  onFullTranscript: () => void
  restoreFocus: () => void
}) {
  const sourceId = call.sourceId ?? call.assessmentVersion?.sourceId
  const check = checks.find((item) => item.id === selection.checkId)
  const selectedCheck = selection.full ? undefined : check
  const title = selectedCheck ? checkTitle(selectedCheck) : selection.full ? 'Full transcript' : 'Evidence'
  const titleRef = useRef<HTMLHeadingElement>(null)
  const [context, setContext] = useState(false)
  const { turns, missing, selected } = transcriptEvidence(
    call.transcript, selection.turns,
    selection.full ? 'full' : context ? 'surrounding' : 'selected',
  )
  const citedTurns = selectedCheck ? checkTurns(selectedCheck) : []
  const showTranscript = !selectedCheck || selection.turns.some((number) => !citedTurns.includes(number))
  const reference = call.references.find(
    (entry) =>
      entry.id === selection.referenceId &&
      referenceIds.includes(entry.id) &&
      canReadKnowledge(entry, call.agentId),
  )
  const backButton = (
    <Button variant="secondary" onClick={onClose}>Back to assessment</Button>
  )
  function focusTitle() {
    titleRef.current?.focus({ preventScroll: true })
  }
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
          className={selectedCheck ? 'evidence-sheet evidence-sheet--check' : 'evidence-sheet'}
          onOpenAutoFocus={(event) => {
            event.preventDefault()
            focusTitle()
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            restoreFocus()
          }}
        >
          <div data-slot="sheet-header">
            <p className="eyebrow">{selectedCheck && `${categoryTitle} · `}Call {sourceId ? `ABCD ${sourceId}` : call.id}</p>
            <Sheet.Title data-slot="sheet-title" ref={titleRef} tabIndex={-1}>{title}</Sheet.Title>
            <Sheet.Description data-slot="sheet-description" className={selectedCheck ? 'sr-only' : undefined}>
              {call.assessmentSource === 'simulation'
                ? 'Archived ABCD passages and assessment sources.'
                : 'Recorded conversation passages and applicable approved reference.'}
            </Sheet.Description>
          </div>
          <div className="sheet-body" key={selection.full ? 'full' : selectedCheck?.id ?? selection.turns.join(',')}>
            {selectedCheck && (
              <CheckEvidenceSummary
                check={selectedCheck}
                checks={checks}
                turns={call.transcript?.turns ?? []}
                title={title}
                onOpen={(number) => {
                  onSelectTurn(number)
                  focusTitle()
                }}
              />
            )}
            {showTranscript && !selection.full && selection.turns.length > 0 && (
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
            {showTranscript && <div className="evidence-thread">
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
            </div>}
            {showTranscript && !turns.length && (
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
            {selection.checkId && !check && <p>Selected check unavailable for this category.</p>}
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
          </div>
          <div data-slot="sheet-footer">
            {selectedCheck && backButton}
            {!selection.full && (
              <Button onClick={() => {
                onFullTranscript()
                focusTitle()
              }}>
                Full transcript
              </Button>
            )}
            {!selectedCheck && backButton}
          </div>
          <Sheet.Close data-slot="sheet-close" className="close-dialog grid-center" aria-label="Close evidence">
            <Icon name="close" size={20} />
          </Sheet.Close>
        </Sheet.Content>
      </Sheet.Portal>
    </Sheet.Root>
  )
}
