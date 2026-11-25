import { useState, type FormEvent } from 'react'
import { canDecideKnowledge, type KnowledgeDraft, type KnowledgeReviewApi } from '../../types/knowledge'

type Decision = 'approve' | 'reject' | 'unapprove'

export function useKnowledgeDecision(api: KnowledgeReviewApi, managerId: string, entry: KnowledgeDraft, canDecide: boolean, onDecided: (entry: KnowledgeDraft) => void) {
  const reference = entry.verificationReference ?? entry.approvalReference ?? null
  const [referenceOpened, setReferenceOpened] = useState(false)
  const [verified, setVerified] = useState(false)
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState<Decision | null>(null)
  const [failed, setFailed] = useState<Decision | null>(null)
  const decisionAllowed = canDecide && api.decisionsAvailable !== false
  const needsDecision = canDecideKnowledge(entry)
  const readyToApprove = entry.authoredPolicyVersion
    ? reference === null
    : Boolean(entry.approvalReference) || (reference !== null && referenceOpened && verified)
  const canApprove = readyToApprove && !entry.duplicateOfId && !entry.possibleConflicts?.length

  async function decide(outcome: Decision) {
    if (saving || !decisionAllowed) return
    if (outcome === 'unapprove' ? entry.status !== 'approved' : !needsDecision) return
    if (outcome === 'approve' && !canApprove) return
    if (outcome === 'reject' && !reason.trim()) return
    setSaving(outcome)
    setFailed(null)
    try {
      switch (outcome) {
        case 'approve':
          onDecided(await api.approve(
            managerId,
            entry.id,
            reference?.url ?? null,
            entry.version,
            entry.authoredPolicyVersion ?? undefined,
          ))
          break
        case 'reject':
          onDecided(await api.reject(managerId, entry.id, reason, entry.version))
          break
        case 'unapprove':
          onDecided(await api.unapprove(managerId, entry.id, entry.version))
          break
      }
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
