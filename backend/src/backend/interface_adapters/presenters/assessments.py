"""Format already-loaded records into the unchanged public read contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from backend.data.demo_profiles import profile_display_name
from backend.entities.results import (
    CRITERION_FOR_CATEGORY,
    CRITERION_TITLES,
    OUTCOME_NAMES,
    RESULT_NAMES,
    Speaker,
)
from backend.interface_adapters.records import (
    AgentContextRecord,
    Audit,
    Conversation,
    FeedbackFlag,
    Finding,
    KnowledgeEntry,
    KnowledgeReview,
    ManagerReview,
    OrganizationMembership,
)
from backend.schemas import (
    AgentContext,
    AuditCriterion,
    CallFinding,
    CallReview,
    ManagerDecision,
    ReviewRequest,
    Transcript,
    TranscriptTurn,
)
from backend.schemas import Conversation as ConversationSummary
from backend.schemas import KnowledgeEntry as KnowledgeEntrySchema
from backend.schemas.call_review import (
    CRITERION_IDS,
    AssessmentVersion,
    CategoryScoring,
    OverallScoring,
    RequestLink,
)
from backend.schemas.conversations import AutomatedResult, ReviewStatus

SPEAKER_NAMES = {
    Speaker.AGENT: "Agent",
    Speaker.CUSTOMER: "Customer",
    Speaker.SYSTEM_ACTION: "System action",
}

NO_TOPIC = "Unassigned"
NO_STORED_RESULT = "No result was stored for this criterion."
NO_VISIBLE_EVIDENCE = (
    "A finding was stored without transcript evidence, so it cannot be shown as "
    "needing review."
)


def iso_date(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.astimezone(UTC).date()
    return value.isoformat()


def iso_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class AgentIdentity:
    """How an agent is named in API responses."""

    id: str
    name: str


def visible_evidence(finding: Finding, conversation_id: int) -> list[int]:
    """Turn numbers a finding cites that are shown in this call's transcript."""
    return sorted(
        {
            turn.line_number
            for turn in finding.evidence
            if turn.conversation_id == conversation_id and turn.speaker in SPEAKER_NAMES
        }
    )


def assessment(
    audit: Audit, conversation_id: int, organization_id: int
) -> tuple[list[AuditCriterion], list[CallFinding], list[KnowledgeEntry]]:
    """Map an audit's stored findings to the frontend's criteria and findings.

    Each criterion keeps the stored result. Two cases are shown as cannot-assess
    instead: a category with no stored finding, and a needs-work finding with no
    evidence in the transcript (the contract never shows a failure without
    evidence). The references are the exact entry versions the findings cite.
    """
    by_criterion = {
        CRITERION_FOR_CATEGORY[finding.category]: finding for finding in audit.findings
    }
    criteria: list[AuditCriterion] = []
    findings: list[CallFinding] = []
    references: dict[int, KnowledgeEntry] = {}

    for criterion_id in CRITERION_IDS:
        finding = by_criterion.get(criterion_id)
        if finding is None:
            criteria.append(
                AuditCriterion(
                    id=criterion_id,
                    title=CRITERION_TITLES[criterion_id],
                    result="cannot-assess",
                    explanation=NO_STORED_RESULT,
                    evidence_turn_numbers=[],
                    finding_id=None,
                    reference_id=None,
                )
            )
            continue

        evidence = visible_evidence(finding, conversation_id)
        result = RESULT_NAMES[finding.result]
        explanation = finding.feedback
        if result == "needs-review" and not evidence:
            result = "cannot-assess"
            explanation = f"{finding.feedback} {NO_VISIBLE_EVIDENCE}"

        entry = finding.knowledge_entry
        reference_id = None
        if entry is not None and entry.organization_id == organization_id:
            references[entry.id] = entry
            reference_id = str(entry.id)

        finding_id = None
        if result == "needs-review":
            finding_id = str(finding.id)
            findings.append(
                CallFinding(
                    id=finding_id,
                    title=finding.feedback,
                    criterion_id=criterion_id,
                    explanation=finding.feedback,
                    suggestion=finding_suggestion(finding),
                    evidence_turn_numbers=evidence,
                    reference_id=reference_id,
                    reference_step=None,
                    procedure_steps=[],
                )
            )
        criteria.append(
            AuditCriterion(
                id=criterion_id,
                title=CRITERION_TITLES[criterion_id],
                result=result,
                explanation=explanation,
                evidence_turn_numbers=evidence,
                finding_id=finding_id,
                reference_id=reference_id,
            )
        )
    return criteria, findings, list(references.values())


def finding_suggestion(finding: Finding) -> str:
    return finding.suggestion or ""


def overall_result(criteria: list[AuditCriterion]) -> AutomatedResult:
    results = {criterion.result for criterion in criteria}
    if "needs-review" in results:
        return "needs-review"
    if "cannot-assess" in results:
        return "cannot-assess"
    return "meets-criteria"


def flags_of(audit: Audit | None) -> list[FeedbackFlag]:
    if audit is None:
        return []
    return [
        finding.feedback_flag
        for finding in audit.findings
        if finding.feedback_flag is not None
    ]


def review_status(audit: Audit | None) -> ReviewStatus | None:
    if audit is None:
        return None
    flags = flags_of(audit)
    if not flags:
        return "feedback-ready"
    if any(flag.manager_review is None for flag in flags):
        return "review-requested"
    return "review-complete"


def latest_decision(audit: Audit | None) -> ManagerDecision | None:
    reviews: list[ManagerReview] = [
        flag.manager_review
        for flag in flags_of(audit)
        if flag.manager_review is not None
    ]
    if not reviews:
        return None
    review = max(reviews, key=lambda review: (review.reviewed_at, review.id))
    return ManagerDecision(
        outcome=OUTCOME_NAMES[review.outcome],
        reason=review.reason,
        feedback=review.feedback,
        manager_name=profile_display_name(
            review.reviewer_membership.user.external_id,
            review.reviewer_membership.user.display_name,
        ),
        decided_at=iso_timestamp(review.reviewed_at),
    )


def transcript_of(conversation: Conversation) -> Transcript | None:
    """Preserve original positions and label recorded actions separately."""
    turns = [
        TranscriptTurn(
            number=turn.line_number,
            speaker=SPEAKER_NAMES[turn.speaker],
            text=turn.text,
            time=None,
        )
        for turn in conversation.turns
        if turn.speaker in SPEAKER_NAMES
    ]
    if not turns:
        return None
    evidence = conversation.canonical_evidence
    complete = (
        evidence["conversations"][0]["coverage"]["transcript"]["status"] == "complete"
        if evidence
        else True
    )
    return Transcript(complete=complete, turns=turns, unavailable_reason=None)


def knowledge_entry_schema(
    entry: KnowledgeEntry, available_to: list[str]
) -> KnowledgeEntrySchema:
    """Map an approved-knowledge row to the frontend's KnowledgeEntry.

    Each approval creates a new entry row, so the approving review identifies
    the version. Fields the database does not store (effective date, owner,
    source, steps) stay empty rather than guessed.
    """
    review: KnowledgeReview = entry.approved_review
    approver = review.reviewer_membership.user if review.reviewer_membership else None
    return KnowledgeEntrySchema(
        id=str(entry.id),
        title=entry.topic.name,
        topic=entry.topic.name,
        kind="knowledge",
        status=entry.status.value,
        available_to_agent_ids=available_to,
        version=f"review-{review.id}",
        approved_at=iso_date(review.reviewed_at),
        approved_by=profile_display_name(approver.external_id, approver.display_name)
        if approver
        else None,
        effective_at=None,
        last_confirmed_at=iso_date(entry.last_confirmed_at),
        owner=None,
        source={
            "title": "Verified approval reference",
            "url": review.verified_reference_url,
        }
        if review.verified_reference_url
        else None,
        paragraphs=[
            paragraph.strip()
            for paragraph in entry.answer_text.split("\n\n")
            if paragraph.strip()
        ],
        steps=[],
    )


def conversation_summary(
    conversation: Conversation,
    audit: Audit | None,
    agent: AgentIdentity,
    report: dict | None = None,
) -> ConversationSummary:
    if audit is None:
        automated: AutomatedResult = "unavailable"
    else:
        criteria, _, _ = assessment(
            audit, conversation.id, conversation.organization_id
        )
        automated = overall_result(criteria)
    return ConversationSummary(
        id=str(conversation.id),
        source_id=conversation.original_id
        if conversation.source_dataset == "ABCD"
        else None,
        topic=conversation.topic.name if conversation.topic else NO_TOPIC,
        agent_id=agent.id,
        agent_name=agent.name,
        date=iso_date(conversation.conversation_date),
        automated_result=automated,
        review_status=review_status(audit),
        overall_scoring=report_overall(audit.assessment_report if audit else report),
    )


def agent_context_schema(context: AgentContextRecord | None) -> AgentContext | None:
    if context is None:
        return None
    return AgentContext(text=context.text, saved_at=iso_timestamp(context.saved_at))


def review_request_schema(flag: FeedbackFlag) -> ReviewRequest:
    return ReviewRequest(
        finding_id=str(flag.finding_id),
        reason=flag.reason,
        requested_at=iso_timestamp(flag.flagged_at),
        status="requested" if flag.manager_review is None else "complete",
    )


def current_flag(audit: Audit | None, finding_ids: set[str]) -> FeedbackFlag | None:
    """The call's review request: the newest open one, else the newest completed one.

    Only flags on findings shown in the call view count.
    """
    flags = [flag for flag in flags_of(audit) if str(flag.finding_id) in finding_ids]
    if not flags:
        return None
    return max(
        flags,
        key=lambda flag: (flag.manager_review is None, flag.flagged_at, flag.id),
    )


def current_review_request(
    audit: Audit | None, finding_ids: set[str]
) -> ReviewRequest | None:
    flag = current_flag(audit, finding_ids)
    return review_request_schema(flag) if flag is not None else None


def call_review(
    conversation: Conversation,
    audit: Audit | None,
    agent: AgentIdentity,
    context: AgentContextRecord | None = None,
    report: dict | None = None,
) -> CallReview:
    common = {
        "id": str(conversation.id),
        "source_id": conversation.original_id
        if conversation.source_dataset == "ABCD"
        else None,
        "agent_id": agent.id,
        "agent_name": agent.name,
        "topic": conversation.topic.name if conversation.topic else NO_TOPIC,
        "date": iso_date(conversation.conversation_date),
        "duration": None,
        "transcript": transcript_of(conversation),
        "agent_context": agent_context_schema(context),
    }
    if audit is None:
        call = CallReview(
            **common,
            summary="",
            status="unavailable",
            criteria=[],
            findings=[],
            references=[],
            review_request=None,
            decision=None,
        )
        return with_scoring(call, report)
    criteria, findings, entries = assessment(
        audit, conversation.id, conversation.organization_id
    )
    call = CallReview(
        **common,
        summary=audit.summary or "",
        status="ready",
        criteria=criteria,
        findings=findings,
        # The versions this call was assessed against, even if since replaced.
        references=[knowledge_entry_schema(entry, [agent.id]) for entry in entries],
        review_request=current_review_request(
            audit, {finding.id for finding in findings}
        ),
        decision=latest_decision(audit),
    )
    return with_scoring(call, audit.assessment_report)


def report_overall(report):
    return OverallScoring.model_validate(report["overall"]) if report else None


def with_scoring(call, report):
    if report is None:
        return call
    prior = {criterion.id: criterion for criterion in call.criteria}
    criteria = []
    for row in report["categories"]:
        category = row["category"]
        result = row["result"]
        criterion = prior.get(category)
        if criterion is None:
            criterion = AuditCriterion(
                id=category,
                title=CRITERION_TITLES[category],
                result=result["result"] if result else "cannot-assess",
                explanation=result["explanation"]
                if result
                else "Processing failed for this category.",
                evidence_turn_numbers=sorted(
                    {
                        citation["turn_id"]
                        for check in row["scoring"]["checks"]
                        for citation in check["citations"]
                        if citation["kind"] == "conversation"
                    }
                ),
                finding_id=None,
                reference_id=None,
            )
        criteria.append(
            criterion.model_copy(
                update={
                    "scoring": CategoryScoring.model_validate(row["scoring"]),
                }
            )
        )
    # A critical check does not make every finding in its category critical.
    findings = list(call.findings)
    priorities = report.get("priorities", [])
    order = {}
    for index, priority in enumerate(priorities):
        order.setdefault(priority["category"], index)
    findings.sort(key=lambda finding: order.get(finding.criterion_id, len(priorities)))
    return call.model_copy(
        update={
            "status": "ready" if call.status == "ready" else "partial",
            "criteria": criteria,
            "overall_scoring": report_overall(report),
            "assessment_version": AssessmentVersion(
                source_id=report["conversation_id"],
                as_of=report["as_of"],
                rules=report["versions"]["rules"],
                scoring_method=report["versions"].get("scoring"),
                transcript=report["transcript_version"],
            ),
            "request_links": [
                RequestLink(
                    id=item["id"],
                    text=next(
                        (
                            turn.text
                            for turn in call.transcript.turns
                            if turn.number == item["turn_id"]
                        ),
                        "Source passage unavailable",
                    )
                    if call.transcript
                    else "Source passage unavailable",
                    state=item["state"],
                    request_turns=sorted(
                        {item["turn_id"], *item.get("context_turn_ids", [])}
                    ),
                    response_turns=sorted(
                        {
                            number
                            for event in item["history"][1:]
                            for number in event["turn_ids"]
                        }
                    ),
                    limitations=[event["reason"] for event in item["history"]],
                )
                for item in report.get("requests", [])
            ],
            "findings": findings,
        }
    )


def agent_identity(membership: OrganizationMembership) -> AgentIdentity:
    return AgentIdentity(
        id=membership.user.external_id,
        name=profile_display_name(
            membership.user.external_id, membership.user.display_name
        ),
    )
