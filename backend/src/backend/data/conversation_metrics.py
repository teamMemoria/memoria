from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

HVB_DATASET = "HarperValleyBank"
ABCD_DATASET = "ABCD"
WORD_PATTERN = re.compile(r"\b\w+(?:['’]\w+)*\b", re.UNICODE)


@dataclass(frozen=True)
class ConversationMetrics:
    """Derived values stored separately from the imported source fields.

    Millisecond metrics require complete timing on every Agent/customer voice
    turn. WER compares case-folded word tokens after punctuation is removed.
    Channel-specific values are None when they are unsupported or unavailable.
    """

    turn_count: int
    agent_word_count: int
    customer_word_count: int
    agent_text_share: float | None
    customer_text_share: float | None
    call_elapsed_ms: int | None
    agent_speaking_ms: int | None
    customer_speaking_ms: int | None
    average_turn_duration_ms: float | None
    asr_word_error_rate: float | None
    asr_compared_turn_count: int | None
    system_action_count: int | None
    documented_action_count: int | None


def _words(text: str) -> list[str]:
    return [match.group().casefold() for match in WORD_PATTERN.finditer(text)]


def _edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for reference_index, reference_word in enumerate(reference, start=1):
        current = [reference_index]
        for hypothesis_index, hypothesis_word in enumerate(hypothesis, start=1):
            substitution_cost = reference_word != hypothesis_word
            current.append(
                min(
                    previous[hypothesis_index] + 1,
                    current[hypothesis_index - 1] + 1,
                    previous[hypothesis_index - 1] + substitution_cost,
                )
            )
        previous = current
    return previous[-1]


def _voice_metrics(turns: list[dict[str, Any]]) -> dict[str, int | float | None]:
    spoken_turns = [
        turn for turn in turns if turn.get("speaker") in {"agent", "customer"}
    ]

    durations_complete = bool(spoken_turns) and all(
        type(turn.get("duration_ms")) is int and turn["duration_ms"] >= 0
        for turn in spoken_turns
    )
    timings_complete = durations_complete and all(
        type(turn.get("start_ms")) is int and turn["start_ms"] >= 0
        for turn in spoken_turns
    )

    agent_speaking_ms: int | None = None
    customer_speaking_ms: int | None = None
    average_turn_duration_ms: float | None = None
    if durations_complete:
        agent_speaking_ms = sum(
            turn["duration_ms"] for turn in spoken_turns if turn["speaker"] == "agent"
        )
        customer_speaking_ms = sum(
            turn["duration_ms"]
            for turn in spoken_turns
            if turn["speaker"] == "customer"
        )
        average_turn_duration_ms = sum(
            turn["duration_ms"] for turn in spoken_turns
        ) / len(spoken_turns)

    call_elapsed_ms: int | None = None
    if timings_complete:
        first_start = min(turn["start_ms"] for turn in spoken_turns)
        last_end = max(turn["start_ms"] + turn["duration_ms"] for turn in spoken_turns)
        call_elapsed_ms = last_end - first_start

    total_errors = 0
    total_reference_words = 0
    compared_turn_count = 0
    for turn in spoken_turns:
        gold_text = turn.get("text")
        asr_text = turn.get("asr_text")
        if not isinstance(gold_text, str) or not isinstance(asr_text, str):
            continue
        reference = _words(gold_text)
        hypothesis = _words(asr_text)
        total_errors += _edit_distance(reference, hypothesis)
        total_reference_words += len(reference)
        compared_turn_count += 1

    asr_word_error_rate = (
        total_errors / total_reference_words if total_reference_words else None
    )

    return {
        "call_elapsed_ms": call_elapsed_ms,
        "agent_speaking_ms": agent_speaking_ms,
        "customer_speaking_ms": customer_speaking_ms,
        "average_turn_duration_ms": average_turn_duration_ms,
        "asr_word_error_rate": asr_word_error_rate,
        "asr_compared_turn_count": compared_turn_count,
    }


def compute_conversation_metrics(record: dict[str, Any]) -> ConversationMetrics:
    """Compute one channel-appropriate metric record for a curated conversation."""

    turns = record["turns"]
    agent_word_count = sum(
        len(_words(turn["text"])) for turn in turns if turn.get("speaker") == "agent"
    )
    customer_word_count = sum(
        len(_words(turn["text"])) for turn in turns if turn.get("speaker") == "customer"
    )
    participant_word_count = agent_word_count + customer_word_count
    agent_text_share = (
        agent_word_count / participant_word_count if participant_word_count else None
    )
    customer_text_share = (
        customer_word_count / participant_word_count if participant_word_count else None
    )

    dataset = record["source"]["dataset"]
    channel = record["channel"]
    voice = {
        "call_elapsed_ms": None,
        "agent_speaking_ms": None,
        "customer_speaking_ms": None,
        "average_turn_duration_ms": None,
        "asr_word_error_rate": None,
        "asr_compared_turn_count": None,
    }
    if dataset == HVB_DATASET and channel == "voice":
        voice = _voice_metrics(turns)

    system_action_count: int | None = None
    documented_action_count: int | None = None
    if dataset == ABCD_DATASET and channel == "chat":
        system_action_count = sum(
            turn.get("speaker") == "system_action" for turn in turns
        )
        documented_actions = record["source_fields"].get("actions_taken")
        if isinstance(documented_actions, list):
            documented_action_count = len(documented_actions)

    return ConversationMetrics(
        turn_count=len(turns),
        agent_word_count=agent_word_count,
        customer_word_count=customer_word_count,
        agent_text_share=agent_text_share,
        customer_text_share=customer_text_share,
        system_action_count=system_action_count,
        documented_action_count=documented_action_count,
        **voice,
    )
