"""Serve generated clips only after the normal conversation access checks."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from starlette.concurrency import run_in_threadpool

from backend.api.calls import get_call
from backend.api.conversations import AgentDep
from backend.api.dependencies import ProvidersDep
from backend.api.reviews import ReviewerDep, get_team_call
from backend.schemas import CallReview
from backend.services.narration import (
    DEFAULT_CACHE,
    clip_identity,
    read_clip,
    text_hash,
)

router = APIRouter()
TextDigest = Annotated[str, Query(pattern=r"^[a-f0-9]{64}$")]


async def narration_response(call: CallReview, number: int, voice: str, digest: str):
    turn = (
        next((item for item in call.transcript.turns if item.number == number), None)
        if call.transcript
        else None
    )
    if turn is None or turn.speaker == "System action":
        raise HTTPException(404, "Narration not found")
    if text_hash(turn.text) != digest:
        raise HTTPException(
            409, "Transcript changed. Refresh before playing narration."
        )
    try:
        identity = clip_identity(turn.text, turn.speaker, voice)
    except ValueError:
        raise HTTPException(422, "Voice does not match participant role") from None
    content = await run_in_threadpool(read_clip, DEFAULT_CACHE, identity)
    if content is None:
        raise HTTPException(
            503, "Generated narration is not prepared for this passage."
        )
    return Response(
        content,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Narration-Type": "synthetic",
        },
    )


@router.get("/api/agent/conversations/{conversation_id}/turns/{number}/narration")
async def agent_narration(
    conversation_id: str,
    number: int,
    voice: str,
    text_sha256: TextDigest,
    user: AgentDep,
    providers: ProvidersDep,
):
    call = await get_call(conversation_id, user, providers)
    return await narration_response(call, number, voice, text_sha256)


@router.get("/api/manager/conversations/{conversation_id}/turns/{number}/narration")
async def manager_narration(
    conversation_id: str,
    number: int,
    voice: str,
    text_sha256: TextDigest,
    user: ReviewerDep,
    providers: ProvidersDep,
):
    detail = await get_team_call(conversation_id, user, providers)
    return await narration_response(detail.call, number, voice, text_sha256)
