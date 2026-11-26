import { useSubmission } from '../../lib/useSubmission'
import { formatTimestamp } from '../../lib/dates'
import { ResourceNotice } from '../../components/ResourceNotice'
import { useKnowledgeDecision } from './controller'
import { useResource } from '../../lib/useResource'
import { useCallback, useId, useRef, useState, type FormEvent } from 'react'
import { useParams, useSearchParams } from 'react-router'
import { BackLink } from '../../components/BackLink'
import { Icon } from '../../components/Icon'
import {
  Button,
  Panel,
  StatusLabel,
  TextAreaField,
} from '../../components/controls'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '../../components/ui/collapsible'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from '../../components/ui/dialog'
import {
  type KnowledgeDraft,
  type KnowledgeDraftContent,
  type KnowledgeReviewApi,
} from '../../types/knowledge'
import type { Viewer } from '../../types/viewer'
import { draftPresentation } from './draftPresentation'
import { queueTabFor, queueTabs } from './draftsQueue'
import { KnowledgeDocument } from './KnowledgeDocument'
import { KnowledgeDraftEditor } from './KnowledgeDraftEditor'
import { KnowledgeSources } from './KnowledgeSources'
import './knowledge-drafts.css'

const sentenceSegmenter = new Intl.Segmenter('en', { granularity: 'sentence' })

function readableParagraphs(paragraph: string) {
  const sentences = Array.from(sentenceSegmenter.segment(paragraph), ({ segment }) => segment)
  const paragraphs: string[] = []
  for (let index = 0; index < sentences.length; index += 2) {
    paragraphs.push(sentences.slice(index, index + 2).join('').trim())
  }
  return paragraphs
}

const statusTone = {
  pending: 'attention',
  approved: 'positive',
  flagged: 'attention',
  rejected: 'neutral',
} as const

function SavedRejection({ entry }: { entry: KnowledgeDraft }) {
  const { decision } = entry
  return (
    <>
      <StatusLabel>Rejected</StatusLabel>
      {decision && (
        <p className="metadata-line">
          <span>{decision.managerName}</span>
          <span>
            {formatTimestamp(decision.decidedAt)}
          </span>
        </p>
      )}
      {decision?.reason && <p>Reason: {decision.reason}</p>}
    </>
  )
}

function ReviewContent({
  api,
  managerId,
  entry,
  canDecide,
  canEdit,
  onDecided,
}: {
  api: KnowledgeReviewApi
  managerId: string
  entry: KnowledgeDraft
  canDecide: boolean
  canEdit?: boolean
  onDecided: (entry: KnowledgeDraft) => void
}) {
  const verifiedId = useId()
  const reasonId = useId()
  const approvalNoteId = useId()
  const { reference, referenceOpened, setReferenceOpened, verified, setVerified, reason, setReason, saving, failed, canDecide: decisionAllowed, needsDecision, canApprove, decide, reject } = useKnowledgeDecision(api, managerId, entry, canDecide, onDecided)
  canDecide = decisionAllowed
  const tab = queueTabFor(entry)
  const { title, layer } = draftPresentation(entry.title, entry.layer)
  const directApproval = Boolean(entry.authoredPolicyVersion || entry.approvalReference)
  const approvalNote = directApproval
    ? null
    : layer === 'layer1'
      ? 'A current policy version is required for approval.'
      : reference
        ? 'Check the verification source before approving.'
          : layer === 'layer2'
            ? 'Verification source needed.'
            : 'Approval requires an authoritative reference.'
  const question = entry.question ?? entry.title
  const [preview, setPreview] = useState<KnowledgeDraftContent | null>(null)
  const initialContent = { title, question, guidance: entry.paragraphs.join('\n\n') }
  const edit = canEdit && canDecide && needsDecision ? api.editDraft : undefined
  const attach = api.attachVerification
  const showDecision = entry.status !== 'approved' || Boolean(entry.duplicateOfId || entry.possibleConflicts?.length)
  const { submit: attachSource, saving: attaching, failed: attachmentError } = useSubmission()

  function attachReference(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!attach) return
    const fields = new FormData(event.currentTarget)
    void attachSource(true, async () => onDecided(await attach(managerId, entry.id, {
      title: String(fields.get('title')),
      url: String(fields.get('url')),
      quote: String(fields.get('quote')),
      version: entry.version,
    })))
  }

  const referenceLink = reference && (
    <a
      className="knowledge-review-reference inline-center"
      href={reference.url}
      target="_blank"
      rel="noreferrer"
      aria-label={`Open verification reference: ${reference.title}`}
      onClick={() => setReferenceOpened(true)}
    >
      <Icon name="link" /> Verification source
    </a>
  )
  const draftText = (
    <div className="knowledge-entry-text">
      {(preview ? preview.guidance.split(/\n\s*\n/) : entry.paragraphs).flatMap(readableParagraphs).map((paragraph, index) => (
        <p key={index}>{paragraph}</p>
      ))}
      {entry.steps.length > 0 && (
        <ol>
          {entry.steps.map((step) => (
            <li key={step.number} value={step.number}>
              {step.text}
            </li>
          ))}
        </ol>
      )}
      {!entry.paragraphs.length && !entry.steps.length && (
        <p>No draft content is available.</p>
      )}
    </div>
  )
  const verification = (
    <>
      {needsDecision && canDecide && !directApproval && entry.canAttachVerification && attach && !reference && (
        <form className="knowledge-review-step" onSubmit={attachReference}>
          <h3>Attach a verification source</h3>
          <label>Source title <input name="title" required maxLength={200} /></label>
          <label>Source URL <input name="url" type="url" required maxLength={2000} /></label>
          <label>Exact policy quotation <textarea name="quote" required maxLength={500} /></label>
          <Button type="submit" variant="secondary" disabled={Boolean(attaching) || saving !== null}>
            {attaching ? 'Saving…' : 'Attach reference'}
          </Button>
          {attachmentError && <p role="alert">Check the policy quotation, source URL and draft version.</p>}
        </form>
      )}
      {needsDecision && canDecide && !directApproval && reference && (
        <Collapsible className="knowledge-verification">
          <CollapsibleTrigger asChild>
            <Button variant="secondary">
              <Icon name="plus" /> Verify reference
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="knowledge-verification-content">
            <h3>Verify and approve</h3>
            <p>
              Check the draft against the authoritative reference before
              approving. Matching conversations do not count as verification.
            </p>
            <p className="metadata-line">
              Verification reference: {reference.title}
            </p>
            <label className="knowledge-review-check flex-center" htmlFor={verifiedId}>
              <input
                id={verifiedId}
                type="checkbox"
                checked={verified}
                disabled={!referenceOpened || saving !== null}
                onChange={(event) => setVerified(event.target.checked)}
              />
              I checked this draft against {reference.title}
            </label>
          </CollapsibleContent>
        </Collapsible>
      )}
    </>
  )

  return (
    <>
      <header className="knowledge-review-title flex-center">
        <h1>{title}</h1>
        <StatusLabel tone={statusTone[tab]}>{queueTabs[tab]}</StatusLabel>
        {entry.status === 'approved' && decisionAllowed && (
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="secondary" className="knowledge-unapprove" disabled={saving !== null}>
                Unapprove
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogTitle>Unapprove this draft?</DialogTitle>
              <DialogDescription>
                The draft will go back to review and disappear from the Agent Knowledge Base.
              </DialogDescription>
              {failed === 'unapprove' && (
                <p role="alert">The draft could not be unapproved. Try again.</p>
              )}
              <div className="knowledge-review-actions flex-center">
                <DialogClose asChild><Button variant="secondary">Cancel</Button></DialogClose>
                <Button
                  loading={saving === 'unapprove'}
                  loadingLabel="Unapproving…"
                  disabled={saving !== null}
                  onClick={() => void decide('unapprove')}
                >
                  Unapprove
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        )}
      </header>
      {api.decisionsAvailable === false && <Panel title="Decision">
        <p>Knowledge drafts are read-only in this demo. Approve and reject are not available yet.</p>
      </Panel>}
      {layer !== 'layer1' && <KnowledgeSources entry={entry} />}
      {layer === 'other' ? (
        <Panel title={title === entry.title ? 'Knowledge entry' : entry.title} className="knowledge-entry">
          {referenceLink}
          {draftText}
          {verification}
        </Panel>
      ) : (
        <>
          <KnowledgeDocument
            title={preview?.title ?? title}
            question={preview?.question ?? question}
            onEdit={edit && !saving && !attaching ? () => setPreview(initialContent) : undefined}
            editor={preview && edit && (
              <KnowledgeDraftEditor
                initial={initialContent}
                onPreview={setPreview}
                onCancel={() => setPreview(null)}
                onSave={async (content) => {
                  onDecided(await edit(managerId, entry.id, { ...content, version: entry.version }))
                  setPreview(null)
                }}
              />
            )}
          >
            {draftText}
            {referenceLink}
          </KnowledgeDocument>
          {!preview && verification}
        </>
      )}
      {showDecision && <Panel title="Decision" className="knowledge-review-decision" hideTitle>
        {entry.duplicateOfId && (
          <p>Resolve duplicate draft {entry.duplicateOfId} before approval.</p>
        )}
        {entry.possibleConflicts?.map((conflict) => (
          <p key={conflict.id}>Unresolved conflict: {conflict.explanation}</p>
        ))}
        {!needsDecision ? (
          entry.status === 'rejected' && <SavedRejection entry={entry} />
        ) : !canDecide ? (
          <p>You do not have permission to approve or reject knowledge.</p>
        ) : (
          <>
            <div className="knowledge-review-actions flex-center">
              {approvalNote && <p id={approvalNoteId} className="metadata-line">{approvalNote}</p>}
              <Button
                aria-describedby={approvalNote ? approvalNoteId : undefined}
                loading={saving === 'approve'}
                loadingLabel="Approving…"
                disabled={!canApprove || saving !== null || preview !== null}
                onClick={() => void decide('approve')}
              >
                Approve
              </Button>
              <Dialog>
                <DialogTrigger asChild>
                  <Button
                    variant="secondary"
                    className="knowledge-review-reject"
                    disabled={saving !== null || preview !== null}
                  >
                    Reject
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogTitle>Reject knowledge draft</DialogTitle>
                  <DialogDescription>
                    A reason is required. Rejected guidance will remain
                    unavailable to Agents.
                  </DialogDescription>
                  <form className="knowledge-review-step" onSubmit={reject}>
                    <TextAreaField
                      id={reasonId}
                      label="Reason for rejection"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      disabled={saving !== null}
                      required
                    />
                    <Button
                      type="submit"
                      variant="secondary"
                      loading={saving === 'reject'}
                      loadingLabel="Rejecting…"
                      disabled={!reason.trim() || saving !== null}
                    >
                      Reject
                    </Button>
                    {failed === 'reject' && (
                      <p role="alert">
                        The decision could not be saved. Please try again.
                      </p>
                    )}
                  </form>
                </DialogContent>
              </Dialog>
            </div>
            {failed === 'approve' && (
              <p role="alert">
                The decision could not be saved. Please try again.
              </p>
            )}
          </>
        )}
      </Panel>}
    </>
  )
}

export function KnowledgeReview({
  viewer,
  api,
}: {
  viewer: Viewer
  api: KnowledgeReviewApi | null
}) {
  const { entryId = '' } = useParams()
  const [params] = useSearchParams()
  const search = params.size ? `?${params}` : ''
  const backLink = useRef<HTMLAnchorElement>(null)
  const read = useCallback(async () => {
    const detail = await api!.getForManager(viewer.id, entryId)
    return detail?.entry.id === entryId ? { ...detail, showApproval: false } : null
  }, [api, viewer.id, entryId])
  const state = useResource(api ? read : null)
  const dismissApproval = () => state.update((detail) => ({ ...detail, showApproval: false }))

  const back = (
    <BackLink ref={backLink} to={`/manager/knowledge${search}`}>
      Knowledge drafts
    </BackLink>
  )

  if (!api || state.status !== 'ready') {
    return (
      <div className="knowledge-drafts">
        {back}
        <h1>Knowledge review</h1>
        {!api ? (
          <Panel title="Knowledge review unavailable">
            <p>Knowledge review is not connected.</p>
          </Panel>
        ) : (
          <ResourceNotice state={state} loading="Loading knowledge entry…" errorTitle="Unable to load knowledge entry"
            error="The entry could not be loaded. Please try again."
            unavailableTitle="Entry unavailable" unavailable="This knowledge entry is not available for review." />
        )}
      </div>
    )
  }

  const { entry, canDecide, canEdit, showApproval } = state.data
  return (
    <div className="knowledge-drafts knowledge-review">
      {back}
      <ReviewContent
        key={`${entry.id}:${entry.version}:${entry.verificationReference?.url}`}
        api={api}
        managerId={viewer.id}
        entry={entry}
        canDecide={canDecide}
        canEdit={canEdit}
        onDecided={(decided) =>
          state.update((previous) => previous.entry.id === decided.id
            ? {
                ...previous,
                entry: decided,
                canEdit: previous.canEdit || (
                  previous.canDecide && previous.entry.status === 'approved' && decided.status === 'draft'
                ),
                showApproval: previous.entry.status !== 'approved' && decided.status === 'approved',
              }
            : previous)
        }
      />
      <Dialog open={showApproval} onOpenChange={(open) => { if (!open) dismissApproval() }}>
        <DialogContent
          className="knowledge-approval-dialog"
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            backLink.current?.focus({ preventScroll: true })
          }}
        >
          <span className="knowledge-approval-icon grid-center"><Icon name="check" size={28} /></span>
          <DialogTitle>Approved</DialogTitle>
          <DialogDescription>Agents can now see this in their Knowledge Base.</DialogDescription>
          <Button onClick={dismissApproval}>Done</Button>
        </DialogContent>
      </Dialog>
    </div>
  )
}
