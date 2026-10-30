"""Pure preparation, masking and validation of local ABCD evidence."""

import json
import re
from hashlib import sha256

ABCD_COMMIT = "6b8700ce67c6b37b062dd7a60abc76d7ef832a97"
ABCD_SHA256 = "005d425e890b30a1cdaf0d29d83b08bb7abf038d90fc4924a12e82228e587789"
CONVERSATION_IDS = ("7921", "8570")
MASKING_VERSION = "4"
MIT_NOTICE = """MIT License

Copyright (c) 2021 ASAPP Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
PERSONAL_FIELDS = {
    "customer_name": "PERSON",
    "account_id": "ACCOUNT_ID",
    "username": "USERNAME",
    "email": "EMAIL",
    "phone": "PHONE",
    "pin_number": "SECRET",
    "password": "SECRET",
    "security_answer": "SECRET",
    "date_of_birth": "DATE",
}
ORDER_FIELDS = {
    "full_address": "ADDRESS",
    "street_address": "ADDRESS",
    "city": "CITY",
    "state": "STATE",
    "zip_code": "POSTCODE",
    "order_id": "ORDER_ID",
    "purchase_date": "PURCHASE_DATE",
}
EVENT_FIELDS = {"turn_id", "kind", "speaker", "text", "source_pointer"}
CONVERSATION_FIELDS = {
    "id",
    "split",
    "source_pointer",
    "transcript_version",
    "coverage",
    "events",
}


def _hash(value) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _source_metadata() -> dict:
    return {
        "dataset": "ABCD",
        "commit": ABCD_COMMIT,
        "path": "data/abcd_v1.1.json",
        "sha256": ABCD_SHA256,
    }


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _labelled_secrets(text: str, metadata_values: set[str]):
    """Read explicit values only; ambiguous boundaries cannot yield safe output."""
    label = re.compile(
        r"\b(?:password|pin(?: number)?|security answer)\s*(?:is|:|=)\s*",
        re.IGNORECASE,
    )
    quotes = {'"': '"', "'": "'", "“": "”", "‘": "’"}
    position = 0
    while match := label.search(text, position):
        start = match.end()
        if start == len(text):
            raise ValueError("A labelled secret has an empty or ambiguous value.")
        if text[start] in quotes:
            end = text.find(quotes[text[start]], start + 1)
            if end < 0 or text[end - 1] == "\\":
                raise ValueError(
                    "A labelled secret has an unclosed or ambiguous quote."
                )
            if not re.match(r"(?:\s|[.,;!?](?:\s|$)|$)", text[end + 1 :]):
                raise ValueError("A labelled secret has an ambiguous value boundary.")
            value = text[start + 1 : end]
            position = end + 1
            quoted = True
        else:
            end = len(text)
            value = text[start:end].strip()
            known_value = _normalized(value) in metadata_values or any(
                value.endswith(mark) and _normalized(value[:-1]) in metadata_values
                for mark in ".!?"
            )
            if not known_value and (
                any(mark in value for mark in ",;\n")
                or re.search(r"[.!?]\s+\S", value)
                or label.search(value)
            ):
                raise ValueError("A labelled secret has an ambiguous value boundary.")
            position = end
            quoted = False
        if not value.strip():
            raise ValueError("A labelled secret has an empty or ambiguous value.")
        yield value, quoted


def mask_texts(texts: list[str], scenario: dict) -> list[str]:
    """Discover explicit secrets before masking every turn, including earlier ones.

    Quoted values have exact boundaries. Unknown unquoted values extend to the
    end of the turn, including punctuation; separators or additional sentences
    make their boundary ambiguous and fail without exporting text. Matching
    metadata can establish the full unquoted value, not an arbitrary prefix.
    This is conservative lexical redaction, not general personal-data detection.
    """
    if not isinstance(scenario, dict):
        raise TypeError("Customer masking metadata must be an object.")
    if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
        raise ValueError("Masking requires a list of text values.")
    replacements, counters = {}, {}
    spellings = set()

    def token(value, kind):
        spellings.add(value)
        key = _normalized(value)
        if kind == "PHONE":
            key = re.sub(r"\D", "", value) or key
        if key not in replacements:
            counters[kind] = counters.get(kind, 0) + 1
            replacements[key] = f"[{kind}_{counters[kind]}]"
        return replacements[key]

    for group, fields in (("personal", PERSONAL_FIELDS), ("order", ORDER_FIELDS)):
        values = scenario.get(group, {})
        if not isinstance(values, dict):
            raise TypeError(f"scenario.{group} must be an object.")
        for field, kind in fields.items():
            value = values.get(field)
            if value is None or value == "":
                continue
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise TypeError(f"scenario.{group}.{field} must be a scalar.")
            value = str(value).strip()
            if not value:
                continue
            replacement = token(value, kind)
            if kind == "PHONE":
                replacements[_normalized(value)] = replacement
            if field == "customer_name":
                for part in value.split():
                    if len(part) > 1:
                        spellings.add(part)
                        replacements.setdefault(_normalized(part), replacement)

    metadata_values = set(replacements)
    for text in texts:
        for value, quoted in _labelled_secrets(text, metadata_values):
            if _normalized(value) in replacements:
                spellings.add(value)
                continue
            if (
                not quoted
                and value[-1] in ".!?"
                and _normalized(value[:-1]) in replacements
            ):
                spellings.add(value[:-1])
                continue
            replacement = token(value, "SECRET")
            if not quoted:
                bare = value
                while bare.endswith((".", "!", "?")):
                    bare = bare[:-1]
                    if bare.strip():
                        spellings.add(bare)
                        replacements.setdefault(_normalized(bare), replacement)

    def literal_pattern(value):
        body = "".join(
            r"\s+" if part.isspace() else re.escape(part)
            for part in re.split(r"(\s+)", value)
        )
        left = r"(?<!\w)" if re.match(r"\w", value) else ""
        right = r"(?!\w)" if re.search(r"\w$", value) else ""
        return left + body + right

    known = "|".join(
        literal_pattern(value)
        for value in sorted(
            spellings | replacements.keys(), key=lambda item: (-len(item), item)
        )
    )
    patterns = [r"(?P<email>[\w.+-]+@(?:[\w-]+\.)+[\w-]+)"]
    patterns.extend(
        (
            r"(?P<phone>(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}(?!\w))",
            r"(?P<identifier>\b(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{8,}\b|\b\d{6,}\b)",
        )
    )
    pattern = re.compile("|".join(patterns), re.IGNORECASE)
    known_pattern = (
        re.compile(r"(?=((?:" + known + r")))", re.IGNORECASE) if known else None
    )

    def replacement(value, kind):
        if kind == "known":
            return replacements.get(_normalized(value)) or token(value, "IDENTIFIER")
        return token(
            value,
            {"email": "EMAIL", "phone": "PHONE", "identifier": "IDENTIFIER"}[kind],
        )

    masked = []
    for text in texts:
        candidates = [
            (*match.span(), match.lastgroup)
            for match in pattern.finditer(text)
            if not (
                match.lastgroup in ("phone", "identifier")
                and re.search(r"[$€£¥]\s*[+-]?\d[\d,.]*$", text[: match.end()])
            )
        ]
        if known_pattern is not None:
            candidates.extend(
                (*match.span(1), "known") for match in known_pattern.finditer(text)
            )
        candidates.sort(key=lambda candidate: (candidate[0], -candidate[1]))
        parts, cursor, index = [], 0, 0
        while index < len(candidates):
            start, end, kind = candidates[index]
            longest = end - start
            index += 1
            while index < len(candidates) and candidates[index][0] < end:
                other_start, other_end, other_kind = candidates[index]
                if other_end - other_start > longest:
                    longest, kind = other_end - other_start, other_kind
                end = max(end, other_end)
                index += 1
            parts.extend((text[cursor:start], replacement(text[start:end], kind)))
            cursor = end
        parts.append(text[cursor:])
        masked.append("".join(parts))
    return masked


def transcript_version(conversation: dict) -> str:
    return _hash(
        {
            field: conversation[field]
            for field in ("id", "split", "source_pointer", "events", "coverage")
        }
        | {
            "masking_version": MASKING_VERSION,
            "source_commit": ABCD_COMMIT,
            "source_sha256": ABCD_SHA256,
        }
    )


def prepare_conversation(
    record: dict, *, split: str, index: int, turn_ids: list[int] | None = None
) -> dict:
    """Coverage describes the supplied record, not unrecorded real-world actions."""
    location = f"/{split}/{index}"
    if (
        not isinstance(split, str)
        or split not in {"train", "dev", "test"}
        or type(index) is not int
        or index < 0
    ):
        raise ValueError("Invalid source split or record position.")
    if not isinstance(record, dict):
        raise TypeError(f"{location}: record must be an object.")
    identifier = record.get("convo_id")
    if (
        type(identifier) not in (int, str)
        or re.fullmatch(r"[0-9]+", str(identifier)) is None
    ):
        raise ValueError(f"{location}: convo_id must be a numeric source ID.")
    original = record.get("original")
    if not isinstance(original, list) or not original:
        raise ValueError(f"{location}/original: expected a nonempty event list.")
    for position, event in enumerate(original):
        if (
            not isinstance(event, (list, tuple))
            or len(event) != 2
            or event[0] not in ("agent", "customer", "action")
            or not isinstance(event[1], str)
            or not event[1].strip()
        ):
            raise ValueError(
                f"{location}/original/{position}: invalid speaker or text."
            )
    delexed = record.get("delexed")
    if delexed is not None:
        if not isinstance(delexed, list) or len(delexed) != len(original):
            raise ValueError(f"{location}/delexed: event alignment is invalid.")
        for position, (event, annotated) in enumerate(zip(original, delexed), 1):
            if (
                not isinstance(annotated, dict)
                or annotated.get("speaker") != event[0]
                or type(annotated.get("turn_count")) is not int
                or annotated["turn_count"] != position
            ):
                raise ValueError(
                    f"{location}/delexed/{position - 1}: turn alignment is invalid."
                )
    all_ids = set(range(1, len(original) + 1))
    if turn_ids is None:
        selected = all_ids
    else:
        if (
            not isinstance(turn_ids, list)
            or not turn_ids
            or any(type(turn) is not int or turn not in all_ids for turn in turn_ids)
            or len(set(turn_ids)) != len(turn_ids)
        ):
            raise ValueError("Selected turn IDs must be unique source positions.")
        selected = set(turn_ids)
    masked = mask_texts([event[1] for event in original], record.get("scenario", {}))
    events = [
        {
            "turn_id": turn,
            "kind": "action" if speaker == "action" else "message",
            "speaker": speaker,
            "text": text,
            "source_pointer": f"{location}/original/{turn - 1}",
        }
        for turn, ((speaker, _), text) in enumerate(zip(original, masked), 1)
        if turn in selected
    ]
    coverage = {}
    for kind, source_speakers in (
        ("transcript", {"agent", "customer"}),
        ("actions", {"action"}),
    ):
        available = {
            turn
            for turn, event in enumerate(original, 1)
            if event[0] in source_speakers
        }
        if not available:
            status, reason = (
                "unknown",
                "No events of this kind were supplied; absence is not failure.",
            )
        elif available <= selected:
            status, reason = (
                "complete",
                "All events of this kind in the source record are retained.",
            )
        else:
            status, reason = (
                "partial",
                "Only some events of this kind in the source record are retained.",
            )
        coverage[kind] = {"status": status, "reason": reason}
    conversation = {
        "id": str(identifier),
        "split": split,
        "source_pointer": location,
        "events": events,
        "coverage": coverage,
    }
    conversation["transcript_version"] = transcript_version(conversation)
    return conversation


def prepare_dataset(
    dataset: dict, source: dict, conversation_ids: tuple[str, ...] = CONVERSATION_IDS
) -> dict:
    """Prepare parsed data after the caller verifies the pinned raw-byte checksum."""
    _validate_source(source)
    if (
        not isinstance(dataset, dict)
        or set(dataset) != {"train", "dev", "test"}
        or any(not isinstance(records, list) for records in dataset.values())
    ):
        raise ValueError("ABCD input must preserve its train, dev and test lists.")
    if (
        not conversation_ids
        or any(not isinstance(value, str) for value in conversation_ids)
        or len(set(conversation_ids)) != len(conversation_ids)
    ):
        raise ValueError("Requested conversation IDs must be unique strings.")
    found = {}
    for split in ("train", "dev", "test"):
        for index, record in enumerate(dataset[split]):
            if not isinstance(record, dict):
                raise TypeError(f"/{split}/{index}: record must be an object.")
            identifier = str(record.get("convo_id"))
            if identifier in conversation_ids:
                if identifier in found:
                    raise ValueError(
                        "A requested conversation ID occurs more than once."
                    )
                found[identifier] = prepare_conversation(
                    record, split=split, index=index
                )
    if set(found) != set(conversation_ids):
        raise ValueError("One or more requested conversation IDs were not supplied.")
    return {
        "schema_version": 1,
        "source": dict(source),
        "masking_version": MASKING_VERSION,
        "conversations": [found[identifier] for identifier in conversation_ids],
        "licence": {"name": "MIT", "notice": MIT_NOTICE},
    }


def _validate_source(source):
    if not isinstance(source, dict) or source != _source_metadata():
        raise ValueError("ABCD source provenance is incomplete or unsupported.")


def validate_evidence(evidence: dict) -> None:
    """Reject unexpected fields rather than forwarding hidden annotations."""
    if (
        not isinstance(evidence, dict)
        or evidence.keys()
        != {"schema_version", "source", "masking_version", "conversations", "licence"}
        or type(evidence["schema_version"]) is not int
        or evidence["schema_version"] != 1
    ):
        raise ValueError("Unsupported evidence schema or fields.")
    if evidence["masking_version"] != MASKING_VERSION:
        raise ValueError(
            "Unsupported masking version; regenerate evidence with prepare."
        )
    _validate_source(evidence["source"])
    if evidence["licence"] != {"name": "MIT", "notice": MIT_NOTICE}:
        raise ValueError("The complete ABCD licence notice is required.")
    conversations = evidence["conversations"]
    if not isinstance(conversations, list) or not conversations:
        raise ValueError("Evidence requires conversation records.")
    seen = set()
    for conversation in conversations:
        if (
            not isinstance(conversation, dict)
            or conversation.keys() != CONVERSATION_FIELDS
        ):
            raise ValueError("Conversation fields are missing or unsupported.")
        identifier, split = conversation["id"], conversation["split"]
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[0-9]+", identifier)
            or identifier in seen
            or not isinstance(split, str)
            or split not in {"train", "dev", "test"}
        ):
            raise ValueError("Conversation IDs or splits are invalid or ambiguous.")
        seen.add(identifier)
        pointer = conversation["source_pointer"]
        if not isinstance(pointer, str) or not re.fullmatch(
            r"/" + split + r"/[0-9]+", pointer
        ):
            raise ValueError("Conversation source position is invalid.")
        coverage = conversation["coverage"]
        if not isinstance(coverage, dict) or coverage.keys() != {
            "transcript",
            "actions",
        }:
            raise ValueError("Transcript and action coverage must be separate.")
        for value in coverage.values():
            if (
                not isinstance(value, dict)
                or value.keys() != {"status", "reason"}
                or value["status"] not in ("complete", "partial", "unknown")
                or not isinstance(value["reason"], str)
                or not value["reason"].strip()
            ):
                raise ValueError("Coverage needs a known state and explanation.")
        events = conversation["events"]
        if not isinstance(events, list) or not events:
            raise ValueError("Conversation evidence requires events.")
        previous = 0
        for event in events:
            if (
                not isinstance(event, dict)
                or event.keys() != EVENT_FIELDS
                or type(event["turn_id"]) is not int
                or event["turn_id"] <= previous
                or event["speaker"] not in ("agent", "customer", "action")
                or event["kind"]
                != ("action" if event["speaker"] == "action" else "message")
                or not isinstance(event["text"], str)
                or not event["text"].strip()
                or event["source_pointer"]
                != f"{pointer}/original/{event['turn_id'] - 1}"
            ):
                raise ValueError("Event fields, order or source positions are invalid.")
            previous = event["turn_id"]
        if conversation["transcript_version"] != transcript_version(conversation):
            raise ValueError("Transcript version does not match the masked evidence.")


def conversation_passages(conversations: list[dict]) -> list[dict]:
    return [
        {
            "id": f"{conversation['id']}:{event['turn_id']}",
            "text": event["text"],
            "citation": {
                "kind": "conversation",
                "conversation_id": conversation["id"],
                "transcript_version": conversation["transcript_version"],
                "turn_id": event["turn_id"],
                "event_kind": event["kind"],
                "quote": event["text"],
            },
        }
        for conversation in conversations
        for event in conversation["events"]
    ]
