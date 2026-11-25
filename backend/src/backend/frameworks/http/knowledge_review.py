from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend.entities.identity import CurrentUser, Permission
from backend.errors import ProviderUnavailableError, RecordNotFoundError
from backend.frameworks.data_access.knowledge_import import (
    ImportRejectedError,
    KnowledgeImportService,
    KnowledgePipelineUnavailableError,
)
from backend.frameworks.data_access.knowledge_review import KnowledgeDecisionRejected
from backend.frameworks.http.auth import require_permission
from backend.frameworks.http.dependencies import ProvidersDep
from backend.interface_adapters.ports import KnowledgeReviewProvider, Providers
from backend.schemas.knowledge_review import (
    AttachVerificationInput,
    DraftQueueStatus,
    EditKnowledgeDraftInput,
    KnowledgeDecisionInput,
    KnowledgeDraft,
    KnowledgeImportResult,
    KnowledgeQueueCounts,
    KnowledgeReviewDetail,
)

router = APIRouter(prefix="/api/manager/knowledge")

# Separate from feedback:review: reviewing calls does not let anyone approve knowledge.
ApproverDep = Annotated[
    CurrentUser, Depends(require_permission(Permission.KNOWLEDGE_APPROVE))
]


def review_provider(providers: Providers) -> KnowledgeReviewProvider:
    # The queue needs the database; the fixtures have no pipeline drafts.
    if providers.knowledge_review is None:
        raise ProviderUnavailableError("no knowledge review provider configured")
    return providers.knowledge_review


def get_knowledge_import(request: Request) -> KnowledgeImportService:
    return request.app.state.knowledge_import


@router.get("/drafts", response_model=list[KnowledgeDraft])
async def list_drafts(
    user: ApproverDep,
    providers: ProvidersDep,
    status_filter: Annotated[DraftQueueStatus, Query(alias="status")] = "all",
    q: Annotated[str, Query(max_length=200)] = "",
    possible_conflicts: Annotated[bool, Query(alias="possibleConflicts")] = False,
) -> list[KnowledgeDraft]:
    """Knowledge drafts in the requester's organization, newest first.

    ``status`` is ``draft`` (pending review), ``approved``, ``rejected`` or
    ``all``; ``possibleConflicts=true`` keeps drafts with a suspected conflict;
    ``q`` searches the ID, topic, question and answer.
    """
    try:
        return await review_provider(providers).list_for_approver(
            user.organization_id, user.user_id, status_filter, q, possible_conflicts
        )
    except RecordNotFoundError:
        return []


@router.get("/drafts/counts", response_model=KnowledgeQueueCounts)
async def count_drafts(
    user: ApproverDep, providers: ProvidersDep
) -> KnowledgeQueueCounts:
    """Counts of the stored drafts by status, for the queue's filters."""
    try:
        return await review_provider(providers).counts(
            user.organization_id, user.user_id
        )
    except RecordNotFoundError:
        return KnowledgeQueueCounts(
            total=0, draft=0, approved=0, rejected=0, with_possible_conflicts=0
        )


@router.get("/drafts/{draft_id}", response_model=KnowledgeReviewDetail)
async def get_draft(
    draft_id: str, user: ApproverDep, providers: ProvidersDep
) -> KnowledgeReviewDetail:
    try:
        detail = await review_provider(providers).get_for_approver(
            user.organization_id, user.user_id, draft_id
        )
    except RecordNotFoundError:
        detail = None
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge draft not found")
    return detail


@router.post("/imports", response_model=KnowledgeImportResult)
async def import_pipeline_output(
    user: ApproverDep,
    service: Annotated[KnowledgeImportService, Depends(get_knowledge_import)],
) -> KnowledgeImportResult:
    """Run the knowledge pipeline for the requester's organization and store its drafts.

    The Layer 2 pilot may publish eligible facts automatically.
    """
    try:
        result = await service.run(user.organization_id, requested_by=user.user_id)
    except KnowledgePipelineUnavailableError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from None
    except ImportRejectedError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except RecordNotFoundError as error:
        # The requester's organization has no stored records yet.
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
    return KnowledgeImportResult(**asdict(result))


@router.put("/drafts/{draft_id}/content", response_model=KnowledgeDraft)
async def edit_draft(
    draft_id: str,
    body: EditKnowledgeDraftInput,
    user: ApproverDep,
    providers: ProvidersDep,
) -> KnowledgeDraft:
    """Replace the editable content of a pending draft at its current version."""
    try:
        return await review_provider(providers).edit_draft(
            user.organization_id, user.user_id, draft_id, body
        )
    except RecordNotFoundError:
        raise HTTPException(404, "Knowledge draft not found") from None
    except KnowledgeDecisionRejected as error:
        raise HTTPException(409, str(error)) from None


@router.put("/drafts/{draft_id}/verification", response_model=KnowledgeDraft)
async def attach_verification(
    draft_id: str,
    body: AttachVerificationInput,
    user: ApproverDep,
    providers: ProvidersDep,
):
    try:
        return await review_provider(providers).attach_verification(
            user.organization_id, user.user_id, draft_id, body
        )
    except RecordNotFoundError:
        raise HTTPException(404, "Knowledge draft not found") from None
    except KnowledgeDecisionRejected as error:
        raise HTTPException(409, str(error)) from None


@router.post("/drafts/{draft_id}/approve", response_model=KnowledgeDraft)
async def approve(
    draft_id: str,
    body: KnowledgeDecisionInput,
    user: ApproverDep,
    providers: ProvidersDep,
):
    return await decide(draft_id, body, user, providers, "approved")


@router.post("/drafts/{draft_id}/reject", response_model=KnowledgeDraft)
async def reject(
    draft_id: str,
    body: KnowledgeDecisionInput,
    user: ApproverDep,
    providers: ProvidersDep,
):
    return await decide(draft_id, body, user, providers, "rejected")


@router.post("/drafts/{draft_id}/unapprove", response_model=KnowledgeDraft)
async def unapprove(
    draft_id: str,
    body: KnowledgeDecisionInput,
    user: ApproverDep,
    providers: ProvidersDep,
):
    """Withdraw published guidance and return its draft to pending review."""
    return await decide(draft_id, body, user, providers, "unapproved")


async def decide(draft_id, body, user, providers, outcome):
    try:
        return await review_provider(providers).decide(
            user.organization_id, user.user_id, draft_id, outcome, body
        )
    except RecordNotFoundError:
        raise HTTPException(404, "Knowledge draft not found") from None
    except KnowledgeDecisionRejected as error:
        raise HTTPException(409, str(error)) from None
