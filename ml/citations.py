"""Check citation fidelity, not reference eligibility or factual correctness."""


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _conversation_issue(citation: dict, conversations: list[dict]) -> str | None:
    matches = [
        conversation
        for conversation in conversations
        if isinstance(conversation, dict)
        and conversation.get("id") == citation["conversation_id"]
    ]
    if not matches:
        return "conversation source was not supplied"
    if len(matches) != 1:
        return "conversation source is ambiguous"

    conversation = matches[0]
    if conversation.get("transcript_version") != citation["transcript_version"]:
        return "transcript version does not match"
    events = conversation.get("events")
    if not isinstance(events, list) or any(
        not isinstance(event, dict)
        or type(event.get("turn_id")) is not int
        or event["turn_id"] < 1
        for event in events
    ):
        return "conversation turn identifiers are invalid"
    turn_ids = [event["turn_id"] for event in events]
    if len(set(turn_ids)) != len(turn_ids):
        return "conversation turn identifiers are ambiguous"

    event = next(
        (event for event in events if event["turn_id"] == citation["turn_id"]),
        None,
    )
    if event is None:
        return "conversation turn was not supplied"
    if event.get("kind") != citation["event_kind"]:
        return "conversation event kind does not match"
    text = event.get("text")
    if not isinstance(text, str) or citation["quote"] not in text:
        return "quotation does not match the supplied masked turn"
    return None


def _reference_issue(citation: dict, references: list[dict]) -> str | None:
    matches = [
        reference
        for reference in references
        if isinstance(reference, dict)
        and reference.get("id") == citation["reference_id"]
    ]
    if not matches:
        return "reference source was not supplied"
    if len(matches) != 1:
        return "reference source is ambiguous"

    reference = matches[0]
    if reference.get("version") != citation["reference_version"]:
        return "reference version does not match"
    if reference.get("section_id") != citation["section_id"]:
        return "reference section does not match"
    text = reference.get("text")
    if not isinstance(text, str) or citation["quote"] not in text:
        return "quotation does not match the supplied reference section"
    return None


def validate_citations(
    citations: list[dict], conversations: list[dict], references: list[dict]
) -> list[str]:
    """Validate exact, nonempty substrings against the sources explicitly supplied."""
    if not isinstance(citations, list):
        return ["citations must be a list"]
    if not isinstance(conversations, list):
        return ["conversation sources must be a list"]
    if not isinstance(references, list):
        return ["reference sources must be a list"]

    fields = {
        "conversation": {
            "conversation_id",
            "transcript_version",
            "turn_id",
            "event_kind",
        },
        "reference": {"reference_id", "reference_version", "section_id"},
    }
    errors = []
    for index, citation in enumerate(citations):
        prefix = f"citation[{index}]: "
        if not isinstance(citation, dict):
            errors.append(prefix + "must be an object")
            continue
        kind = citation.get("kind")
        if not isinstance(kind, str) or kind not in fields:
            errors.append(prefix + "kind must be conversation or reference")
            continue
        expected = fields[kind] | {"kind", "quote"}
        if set(citation) != expected:
            errors.append(prefix + "fields do not match the citation schema")
            continue
        text_fields = expected - {"turn_id"}
        if any(not _nonempty_text(citation[field]) for field in text_fields):
            errors.append(prefix + "text fields must be nonempty strings")
            continue

        if kind == "conversation":
            if type(citation["turn_id"]) is not int or citation["turn_id"] < 1:
                errors.append(prefix + "turn_id must be a positive integer")
                continue
            if citation["event_kind"] not in {"message", "action"}:
                errors.append(prefix + "event_kind must be message or action")
                continue
            issue = _conversation_issue(citation, conversations)
        else:
            issue = _reference_issue(citation, references)
        if issue:
            errors.append(prefix + issue)
    return errors
