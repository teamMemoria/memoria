import { useState, type FormEvent } from 'react'
import { canDecideKnowledge, type KnowledgeDraft, type KnowledgeReviewApi } from '../../types/knowledge'

export function useKnowledgeDecision(api: KnowledgeReviewApi, managerId: string, entry: KnowledgeDraft, canDecide: boolean, onDecided: (entry: KnowledgeDraft) => void) {
  const reference = entry.verificationReference
  const [referenceOpened, setReferenceOpened] = useState(false)
  const [verified, setVerified] = useState(false)
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState<'approve' | 'reject' | null>(null)
  const [failed, setFailed] = useState<'approve' | 'reject' | null>(null)
  const decisionAllowed = canDecide && api.decisionsAvailable !== false
  const needsDecision = canDecideKnowledge(entry)
  const canApprove =
    reference !== null &&
    referenceOpened &&
    verified &&
    !entry.duplicateOfId &&
    !entry.possibleConflicts?.length

  async function decide(outcome: 'approve' | 'reject') {
    if (saving || !decisionAllowed || !needsDecision) return
    if (outcome === 'approve' && !canApprove) return
    if (outcome === 'reject' && !reason.trim()) return
    setSaving(outcome)
    setFailed(null)
    try {
      onDecided(
        outcome === 'approve'
          ? await api.approve(
              managerId,
              entry.id,
              reference!.url,
              entry.version,
            )
          : await api.reject(managerId, entry.id, reason, entry.version),
      )
    } catch {
      setFailed(outcome)
      setSaving(null)
    }
  }

  function reject(event: FormEvent) {
    event.preventDefault()
    void decide('reject')
  }

  return { reference, referenceOpened, setReferenceOpened, verified, setVerified, reason, setReason, saving, failed, canDecide: decisionAllowed, needsDecision, canApprove, decide, reject }
}
