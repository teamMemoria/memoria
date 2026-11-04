"""Read ABCD conversations directly from JSON.

Two record shapes are accepted, both read without any backend code:

* the curated shape (``id``, ``source``, ``turns`` ...) used by the team's curated
  set, see ``data/abcd/SOURCE.md``;
* the raw ABCD v1.1 shape (``convo_id``, ``scenario``, ``original``, ``delexed``)
  from https://github.com/asappresearch/abcd.

Both become a :class:`Conversation` that keeps the source and its version,
ordered turn IDs, the recorded agent actions and how much of the record was
kept (evidence coverage). The customer record is kept only so that personal
details can be removed later; it is never copied into an output.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import PipelineError, invalid, oversized

ABCD_COMMIT = "6b8700ce67c6b37b062dd7a60abc76d7ef832a97"
ABCD_VERSION = f"abcd_v1.1@{ABCD_COMMIT[:12]}"
CURATED_COMMIT = "c39d2e0610417256bf05811b774d400deea7456f"
CURATED_VERSION = f"genesys-curated@{CURATED_COMMIT[:12]}"

SPEAKERS = frozenset({"agent", "customer", "system_action"})
# SYNTHETIC records are made-up conversations written for tests; they follow the
# curated shape so the same reader is exercised.
CURATED_DATASETS = frozenset({"ABCD", "SYNTHETIC"})
RAW_SPEAKERS = {"agent": "agent", "customer": "customer", "action": "system_action"}

# Size limits. Anything larger is refused with ``oversized_input`` rather than
# truncated, so a caller never mistakes a partial read for a complete one.
MAX_TURNS = 400
MAX_TURN_CHARS = 4_000
MAX_CONVERSATION_CHARS = 120_000
MAX_BATCH_CONVERSATIONS = 1_000


@dataclass(frozen=True)
class Turn:
    turn_id: str
    n: int
    speaker: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "n": self.n,
            "speaker": self.speaker,
            "text": self.text,
        }


@dataclass(frozen=True)
class Action:
    """An action the agent recorded in their tooling (ABCD ``actions_taken``)."""

    name: str
    order: int
    turn_id: str | None  # the system_action turn it was aligned to, if any

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "order": self.order, "turn_id": self.turn_id}


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    company_id: str
    source: dict[str, Any]
    scope: dict[str, str]
    turns: tuple[Turn, ...]
    actions: tuple[Action, ...]
    coverage: dict[str, Any]
    customer_record: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def source_key(self) -> str:
        """Identity of the underlying source conversation.

        The same ABCD conversation read from the curated file and from the raw
        dump has the same key, so it is never counted twice.
        """
        return f"{self.source['dataset']}:{self.source['original_id']}"

    def turn(self, turn_id: str) -> Turn:
        for turn in self.turns:
            if turn.turn_id == turn_id:
                return turn
        raise KeyError(turn_id)

    def summary(self) -> dict[str, Any]:
        """Everything about the conversation except its text and customer record."""
        return {
            "conversation_id": self.conversation_id,
            "company_id": self.company_id,
            "source": dict(self.source),
            "source_key": self.source_key,
            "scope": dict(self.scope),
            "turn_ids": [t.turn_id for t in self.turns],
            "actions": [a.to_dict() for a in self.actions],
            "coverage": dict(self.coverage),
        }


def _turn_id(conversation_id: str, n: int) -> str:
    return f"{conversation_id}#t{n}"


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid(field_name, "must be a non-empty string")
    return value


def _check_company(company_id: Any) -> str:
    company = _require_str(company_id, "company_id")
    if len(company) > 128:
        raise invalid("company_id", "must be at most 128 characters")
    return company


def _check_sizes(turns: Sequence[tuple[str, str]], prefix: str) -> None:
    if not turns:
        raise invalid(prefix, "must contain at least one turn")
    for index, (_, text) in enumerate(turns):
        try:
            text.encode("utf-8")
        except UnicodeEncodeError as error:
            # A lone surrogate cannot be written out as JSON text later on.
            raise invalid(
                f"{prefix}[{index}].text", "is not valid Unicode text"
            ) from error
    if len(turns) > MAX_TURNS:
        raise oversized(prefix, f"has {len(turns)} turns; the limit is {MAX_TURNS}")
    total = 0
    for index, (_, text) in enumerate(turns):
        if len(text) > MAX_TURN_CHARS:
            raise oversized(
                f"{prefix}[{index}].text",
                f"has {len(text)} characters; the limit is {MAX_TURN_CHARS}",
            )
        total += len(text)
    if total > MAX_CONVERSATION_CHARS:
        raise oversized(
            prefix, f"has {total} characters; the limit is {MAX_CONVERSATION_CHARS}"
        )


def _align_actions(
    names: Sequence[str], turns: Sequence[Turn]
) -> tuple[tuple[Action, ...], int]:
    """Pair recorded actions with system_action turns, in order.

    ABCD records each action both as a name (``actions_taken``) and as a system
    message in the transcript. When the two counts agree they are paired in
    order; when they do not, the actions are kept without a turn so nothing is
    paired by guesswork.
    """
    system_turns = [t for t in turns if t.speaker == "system_action"]
    if len(system_turns) == len(names):
        actions = tuple(
            Action(name=name, order=i + 1, turn_id=turn.turn_id)
            for i, (name, turn) in enumerate(zip(names, system_turns, strict=True))
        )
        return actions, len(actions)
    return tuple(
        Action(name=name, order=i + 1, turn_id=None) for i, name in enumerate(names)
    ), 0


def _coverage(
    turns: Sequence[Turn], actions: Sequence[Action], aligned: int, source_turns: int
) -> dict[str, Any]:
    speakers = Counter(t.speaker for t in turns)
    return {
        "source_turns": source_turns,
        "turns_kept": len(turns),
        "speakers": dict(sorted(speakers.items())),
        "actions_recorded": len(actions),
        "actions_aligned_to_turns": aligned,
    }


def _read_curated(record: Mapping[str, Any], company_id: str) -> Conversation:
    conversation_id = _require_str(record.get("id"), "id")
    source = record.get("source")
    if not isinstance(source, Mapping):
        raise invalid("source", "must be an object")
    dataset = source.get("dataset")
    if dataset not in CURATED_DATASETS:
        raise invalid(
            "source.dataset",
            "must be ABCD (or SYNTHETIC for authored test conversations)",
        )
    raw_original = source.get("original_id")
    if type(raw_original) not in (str, int) or str(raw_original).strip() == "":
        raise invalid("source.original_id", "must be a non-empty string or integer")
    original_id = str(raw_original)

    raw_turns = record.get("turns")
    if not isinstance(raw_turns, list):
        raise invalid("turns", "must be an array")
    pairs: list[tuple[str, str]] = []
    numbers: list[int] = []
    for index, turn in enumerate(raw_turns):
        if not isinstance(turn, Mapping):
            raise invalid(f"turns[{index}]", "must be an object")
        n = turn.get("n")
        if type(n) is not int or n < 1:
            raise invalid(f"turns[{index}].n", "must be a positive integer")
        if numbers and n <= numbers[-1]:
            raise invalid(
                f"turns[{index}].n", "must be greater than the previous turn number"
            )
        speaker = turn.get("speaker")
        if speaker not in SPEAKERS:
            raise invalid(
                f"turns[{index}].speaker", "must be agent, customer or system_action"
            )
        text = turn.get("text")
        if not isinstance(text, str):
            raise invalid(f"turns[{index}].text", "must be a string")
        numbers.append(n)
        pairs.append((speaker, text))
    _check_sizes(pairs, "turns")

    turns = tuple(
        Turn(_turn_id(conversation_id, n), n, speaker, text)
        for n, (speaker, text) in zip(numbers, pairs, strict=True)
    )
    fields = record.get("source_fields")
    if not isinstance(fields, Mapping):
        raise invalid("source_fields", "must be an object")
    flow = _require_str(fields.get("flow"), "source_fields.flow")
    subflow = _require_str(fields.get("subflow"), "source_fields.subflow")
    names = fields.get("actions_taken", [])
    if not isinstance(names, list) or not all(isinstance(a, str) for a in names):
        raise invalid("source_fields.actions_taken", "must be an array of strings")
    actions, aligned = _align_actions(names, turns)

    modifications = record.get("modifications", [])
    if not isinstance(modifications, list):
        raise invalid("modifications", "must be an array")
    customer = _customer_record(record)
    return Conversation(
        conversation_id=conversation_id,
        company_id=company_id,
        source={
            "dataset": dataset,
            "original_id": original_id,
            "record_format": "curated",
            "version": str(
                source.get("version")
                or (CURATED_VERSION if dataset == "ABCD" else "authored")
            ),
            "dataset_version": ABCD_VERSION if dataset == "ABCD" else "authored",
            "split": record.get("split") or source.get("split"),
            "licence": source.get(
                "licence", "MIT" if dataset == "ABCD" else "MIT (this repository)"
            ),
            "url": source.get(
                "url",
                "https://github.com/asappresearch/abcd" if dataset == "ABCD" else "",
            ),
            "modifications": list(modifications),
        },
        scope={"flow": flow, "subflow": subflow},
        turns=turns,
        actions=actions,
        coverage=_coverage(turns, actions, aligned, len(raw_turns)),
        customer_record=customer,
    )


# The customer-record fields the redactor knows. Anything else is refused, so a
# renamed field ("name", "phone_number") cannot slip past redaction unnoticed.
CUSTOMER_FIELDS = {
    "customer_name",
    "member_level",
    "phone",
    "email",
    "username",
    "account_id",
    "address",
    "order",
}
_NESTED_FIELDS = {
    "address": {"street", "city", "state", "zip_code", "full_address"},
    "order": {
        "order_id",
        "purchase_date",
        "num_products",
        "products",
        "payment_method",
        "packaging",
    },
}


def _customer_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """The record's customer details, checked so that redaction can rely on them.

    Without a record nothing could be redacted, so a missing one is an error
    rather than an empty record. A conversation with no personal details says
    so with an empty object.
    """
    if "customer_record" not in record:
        raise invalid("customer_record", "is required (use {} when there is none)")
    customer = record["customer_record"]
    if not isinstance(customer, Mapping):
        raise invalid("customer_record", "must be an object")
    unknown = sorted(set(customer) - CUSTOMER_FIELDS)
    if unknown:
        raise invalid("customer_record", f"has unknown fields: {', '.join(unknown)}")
    for key, value in customer.items():
        if key in _NESTED_FIELDS:
            if value is None:
                continue
            if not isinstance(value, Mapping):
                raise invalid(f"customer_record.{key}", "must be an object")
            unknown = sorted(set(value) - _NESTED_FIELDS[key])
            if unknown:
                raise invalid(
                    f"customer_record.{key}",
                    f"has unknown fields: {', '.join(unknown)}",
                )
        elif value is not None and not isinstance(value, str):
            raise invalid(f"customer_record.{key}", "must be a string")
    return dict(customer)


def _raw_customer(scenario: Mapping[str, Any]) -> dict[str, Any]:
    personal = scenario.get("personal") or {}
    order = scenario.get("order") or {}
    if not isinstance(personal, Mapping):
        raise invalid("scenario.personal", "must be an object")
    if not isinstance(order, Mapping):
        raise invalid("scenario.order", "must be an object")
    record: dict[str, Any] = {k: v for k, v in personal.items() if isinstance(v, str)}
    record["address"] = {
        "street": order.get("street_address"),
        "city": order.get("city"),
        "state": order.get("state"),
        "zip_code": order.get("zip_code"),
        "full_address": order.get("full_address"),
    }
    record["order"] = {
        "order_id": order.get("order_id"),
        "purchase_date": order.get("purchase_date"),
    }
    return record


def _read_raw(record: Mapping[str, Any], company_id: str) -> Conversation:
    convo_id = record.get("convo_id")
    if type(convo_id) is not int:
        raise invalid("convo_id", "must be an integer")
    conversation_id = f"ABCD-raw-{convo_id}"
    scenario = record.get("scenario")
    if not isinstance(scenario, Mapping):
        raise invalid("scenario", "must be an object")
    original = record.get("original")
    if not isinstance(original, list):
        raise invalid("original", "must be an array")
    pairs: list[tuple[str, str]] = []
    for index, item in enumerate(original):
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(part, str) for part in item)
        ):
            raise invalid(f"original[{index}]", "must be a [speaker, text] pair")
        speaker = RAW_SPEAKERS.get(item[0])
        if speaker is None:
            raise invalid(f"original[{index}][0]", "must be agent, customer or action")
        pairs.append((speaker, item[1]))
    _check_sizes(pairs, "original")
    turns = tuple(
        Turn(_turn_id(conversation_id, i + 1), i + 1, speaker, text)
        for i, (speaker, text) in enumerate(pairs)
    )
    names: list[str] = []
    delexed = record.get("delexed")
    if isinstance(delexed, list):
        for item in delexed:
            targets = item.get("targets") if isinstance(item, Mapping) else None
            if (
                isinstance(targets, list)
                and len(targets) > 2
                and targets[1] == "take_action"
                and isinstance(targets[2], str)
            ):
                names.append(targets[2])
    actions, aligned = _align_actions(names, turns)
    flow = _require_str(scenario.get("flow"), "scenario.flow")
    subflow = _require_str(scenario.get("subflow"), "scenario.subflow")
    return Conversation(
        conversation_id=conversation_id,
        company_id=company_id,
        source={
            "dataset": "ABCD",
            "original_id": str(convo_id),
            "record_format": "raw",
            "version": ABCD_VERSION,
            "dataset_version": ABCD_VERSION,
            "split": record.get("split"),
            "licence": "MIT",
            "url": "https://github.com/asappresearch/abcd",
            "modifications": [],
        },
        scope={"flow": flow, "subflow": subflow},
        turns=turns,
        actions=actions,
        coverage=_coverage(turns, actions, aligned, len(original)),
        customer_record=_raw_customer(scenario),
    )


def read_conversation(record: Any, company_id: str) -> Conversation:
    """Read one ABCD record (curated or raw). Raises ``PipelineError`` on bad input."""
    company = _check_company(company_id)
    if not isinstance(record, Mapping):
        raise invalid("$", "conversation must be a JSON object")
    if "convo_id" in record:
        return _read_raw(record, company)
    if "id" in record and "turns" in record:
        return _read_curated(record, company)
    raise invalid(
        "$",
        "not an ABCD record: expected curated (id, turns) or raw (convo_id, original)",
    )


def read_conversations(records: Any, company_id: str) -> list[Conversation]:
    if not isinstance(records, list):
        raise invalid("conversations", "must be an array")
    if len(records) > MAX_BATCH_CONVERSATIONS:
        raise oversized(
            "conversations",
            f"has {len(records)} conversations; the limit is {MAX_BATCH_CONVERSATIONS}",
        )
    out = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        try:
            conversation = read_conversation(record, company_id)
        except PipelineError as error:
            error.field = f"conversations[{index}].{error.field}".rstrip(".$")
            raise
        if conversation.conversation_id in seen:
            raise invalid(
                f"conversations[{index}].id", "duplicate conversation id in one batch"
            )
        seen.add(conversation.conversation_id)
        out.append(conversation)
    return out


def load_split_index(path: Path) -> dict[str, str]:
    """Map curated id -> ABCD split (train/dev/test), from ``data/abcd/splits.json``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: value["split"] for key, value in data.items()}


def load_curated_directory(
    directory: Path, company_id: str, splits: Path | None = None
) -> list[Conversation]:
    """Read every ``*.json`` curated record in a directory, in file-name order."""
    split_index = load_split_index(splits) if splits else {}
    records = []
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("id") in split_index:
            record = {**record, "split": split_index[record["id"]]}
        records.append(record)
    return read_conversations(records, company_id)
