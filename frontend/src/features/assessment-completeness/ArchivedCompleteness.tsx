import { useState } from 'react'
import { Card } from '../../components/ui/card'
import { Icon } from '../../components/Icon'
import { CheckList, EvidenceLink, EvidenceNotes, MaterialLimits, Quote, ScoreCard } from '../assessment-shared/AssessmentElements'
import { ConversationChart } from '../assessment-shared/ConversationChart'
import { checkLabels, checkTitle, linkedCheckTurns, type ScreenProps } from '../assessment-shared/assessment'

export function ArchivedCompleteness({ data, onOpen }: ScreenProps) {
  const [selectedId, setSelectedId] = useState<string>()
  const requests = data.checks
    .filter((check) => check.ruleId === 'completeness.direct_response' && check.outcome !== 'not-applicable')
    .map((check) => ({ check, turns: linkedCheckTurns(data, check) }))
    .filter(({ turns }) => turns.some((turn) => turn.speaker === 'Customer'))
  const selected = requests.find(({ check }) => check.id === selectedId) ?? requests[0]
  const otherChecks = data.checks.filter((check) => !requests.some((request) => request.check.id === check.id))
  const turns = selected?.turns ?? []
  const numbers = turns.map((turn) => turn.number)
  const actions = turns.filter((turn) => turn.speaker === 'System action')
  const request = turns[0]?.speaker === 'Customer' ? turns[0] : undefined
  const agentTurns = turns.filter((turn) => turn.speaker === 'Agent')
  // The archive groups evidence by check. Only preview a pair when there is one
  // cited Agent passage after the opening cited Customer passage.
  const response = request && agentTurns.length === 1 ? agentTurns[0] : undefined
  const progress = selected?.check.outcome === 'partial'
    ? actions.find((turn) => /^purchase validation in progress\b/i.test(turn.text))
    : undefined

  return (
    <>
      <section className="dashboard-top dashboard-top--wide" aria-label="Request completeness checks">
        <ScoreCard data={data} label="Requests" />
        <Card className="dashboard-card action-area request-coverage">
          <h2>Agent actions</h2>
          {requests.length > 0 && (
            <div className="request-list request-list--archived">
              {requests.map(({ check, turns: linked }) => (
                <button key={check.id} onClick={() => {
                  setSelectedId(check.id)
                  onOpen(linked.map((turn) => turn.number), undefined, undefined, check.id)
                }}>
                  <span className="request-icon"><Icon name="document" size={20} /></span>
                  <strong>{checkTitle(check)}</strong>
                  <small>Linked turns {linked.map((turn) => turn.number).join(', ')}</small>
                  <span className={`mini-status mini-status--${check.outcome === 'breach' ? 'attention' : 'neutral'}`}>
                    {checkLabels[check.outcome]}
                  </span>
                </button>
              ))}
            </div>
          )}
          {!requests.length && <p className="card-subtitle">No linked customer request evidence was recorded.</p>}
          {(!requests.length || otherChecks.length > 0) && (
            <CheckList checks={otherChecks} onOpen={onOpen} />
          )}
        </Card>
      </section>
      {selected && (
        <section className="evidence-section evidence-section--plain" aria-labelledby="completeness-evidence-title">
          <div className="section-heading">
            <h2 id="completeness-evidence-title">Evidence</h2>
            <EvidenceLink turns={numbers} checkId={selected.check.id} onOpen={onOpen}>
              View linked turns
            </EvidenceLink>
          </div>
          <ConversationChart
            turns={data.call.transcript?.turns ?? []}
            events={numbers}
            label="Cited passages"
            colour="#16815c"
            onSelect={(turn) => onOpen([turn], undefined, undefined, selected.check.id)}
          />
          {actions.length > 0 && (
            <ul className="linked-actions" aria-label="Linked system actions">
              {actions.map((turn) => (
                <li key={turn.number}>
                  <EvidenceLink turns={[turn.number]} checkId={selected.check.id} onOpen={onOpen}>
                    <small>Turn {turn.number}</small>
                    <strong>{turn.text}</strong>
                  </EvidenceLink>
                </li>
              ))}
            </ul>
          )}
          <div className="quote-pair">
            {(request && response ? [request, response] : turns.slice(0, 2)).map((turn) => (
              <Quote key={turn.number} turn={turn} onOpen={(selectedTurns) =>
                onOpen(selectedTurns, undefined, undefined, selected.check.id)
              } />
            ))}
          </div>
          {request && response && (
            <div className="completion-strip">
              <span className="assessment-metadata"><span>Customer</span><span>Turn {request.number}</span></span>
              <i />
              <span className="assessment-metadata"><span>Agent</span><span>Turn {response.number}</span></span>
            </div>
          )}
          <EvidenceNotes data={data} />
          <MaterialLimits data={data} />
        </section>
      )}
      {!selected && <MaterialLimits data={data} />}
      {progress && selected && (
        <section className="coaching" aria-label="What remains unverified">
          <div className="coaching-summary">
            <span className="coaching-icon"><Icon name="info" size={23} /></span>
            <div>
              <h2>What remains unverified</h2>
              <p>Purchase validation is recorded as in progress in the linked evidence.</p>
              <EvidenceLink turns={[progress.number]} checkId={selected.check.id} onOpen={onOpen}>
                View turn {progress.number}
              </EvidenceLink>
            </div>
          </div>
        </section>
      )}
    </>
  )
}
