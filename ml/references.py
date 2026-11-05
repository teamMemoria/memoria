"""Reference trust rules and deterministic search over explicitly supplied passages."""

import json
import re
from datetime import date
from hashlib import sha256

CONTENT_FIELDS = (
    "id",
    "section_id",
    "title",
    "text",
    "conditions",
    "exclusions",
    "scope",
    "source",
    "safety_flags",
)
RECORD_FIELDS = set(CONTENT_FIELDS) | {
    "version",
    "status",
    "approved_by",
    "approved_version",
    "approved_at",
    "verified_at",
    "review_due",
}
OPTIONAL_CONTENT_FIELDS = {"interpretation_limits"}
SOURCE_FIELDS = {"dataset", "commit", "path", "sha256", "pointer"}
STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "what",
        "with",
    ]
)


def _has_text_fields(value, fields):
    return isinstance(value, dict) and all(
        isinstance(value.get(field), str) and value[field].strip() for field in fields
    )


def _text_list(value):
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _valid_scope(scope):
    return isinstance(scope, str) and bool(scope.strip()) and scope == scope.strip()


def reference_version(reference: dict) -> str:
    """Version content and provenance, not mutable human-review metadata."""
    if not isinstance(reference, dict) or not set(CONTENT_FIELDS) <= reference.keys():
        raise ValueError("Reference content fields are missing.")
    try:
        content = {field: reference[field] for field in CONTENT_FIELDS}
        for field in OPTIONAL_CONTENT_FIELDS & reference.keys():
            content[field] = reference[field]
        encoded = json.dumps(
            content,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ValueError("Reference content must contain JSON values.") from None
    return "sha256:" + sha256(encoded).hexdigest()


def _day(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _context(as_of, scope):
    assessment_day = _day(as_of)
    if assessment_day is None:
        raise ValueError("as_of must be an explicit YYYY-MM-DD date.")
    if not _valid_scope(scope):
        raise ValueError("scope must be a nonempty, trimmed string.")
    return assessment_day


def reference_issues(reference: dict, *, as_of: str, scope: str) -> list[str]:
    """Fail closed when approval, currentness, scope or integrity is unknown."""
    _context(as_of, scope)
    if (
        not isinstance(reference, dict)
        or reference.keys() - OPTIONAL_CONTENT_FIELDS != RECORD_FIELDS
    ):
        return ["Reference fields are missing or unsupported."]
    issues = []
    text_fields = ("id", "section_id", "title", "text", "version")
    if not _has_text_fields(reference, text_fields):
        issues.append("Reference identifiers and text must be nonempty strings.")
    list_fields = ["conditions", "exclusions", "scope", "safety_flags"]
    list_fields.extend(OPTIONAL_CONTENT_FIELDS & reference.keys())
    if any(not _text_list(reference[field]) for field in list_fields):
        return issues + ["Reference conditions, scope and flags must be string lists."]
    source = reference["source"]
    if (
        not isinstance(source, dict)
        or source.keys() != SOURCE_FIELDS
        or any(
            not isinstance(value, str) or not value.strip() for value in source.values()
        )
        or source.get("dataset") != "ABCD"
        or not re.fullmatch(r"[a-f0-9]{40}", source.get("commit", ""))
        or not re.fullmatch(r"[a-f0-9]{64}", source.get("sha256", ""))
        or not source.get("pointer", "").startswith("/")
    ):
        issues.append("Reference source provenance is incomplete or invalid.")
    try:
        if reference["version"] != reference_version(reference):
            issues.append("Reference version does not match its content.")
    except ValueError:
        issues.append("Reference content is not valid JSON.")
    return issues + review_issues(reference, as_of=as_of, scope=scope)


def review_issues(reference: dict, *, as_of: str, scope: str) -> list[str]:
    """Check review metadata; callers must also validate content and provenance."""
    assessment_day = _context(as_of, scope)
    fields = {
        "version",
        "status",
        "approved_by",
        "approved_version",
        "approved_at",
        "verified_at",
        "review_due",
        "scope",
        "exclusions",
        "safety_flags",
    }
    if not isinstance(reference, dict) or not fields <= reference.keys():
        return ["Review metadata is missing."]
    if any(
        not _text_list(reference[field])
        for field in ("scope", "exclusions", "safety_flags")
    ):
        return ["Review scope and flags must be text lists."]
    issues = []
    if reference["status"] != "approved":
        issues.append("Reference is not approved.")
    if reference["approved_version"] != reference["version"]:
        issues.append("Approval does not cover this reference version.")
    if not _has_text_fields(reference, ("approved_by",)):
        issues.append("Human approver is not recorded.")
    approved_at = _day(reference["approved_at"])
    verified_at = _day(reference["verified_at"])
    review_due = _day(reference["review_due"])
    if approved_at is None or approved_at > assessment_day:
        issues.append("Approval date is unknown, invalid or after the assessment date.")
    if verified_at is None or verified_at > assessment_day:
        issues.append(
            "Verification date is unknown, invalid or after the assessment date."
        )
    if review_due is None or review_due < assessment_day:
        issues.append(
            "Currentness is unknown or the human-set review deadline has passed."
        )
    if verified_at and review_due and review_due < verified_at:
        issues.append("Review deadline precedes verification.")
    if scope not in reference["scope"] or scope in reference["exclusions"]:
        issues.append("Reference is outside the requested scope.")
    if reference["safety_flags"]:
        issues.append(
            "Unsafe benchmark instructions require human correction and review."
        )
    return issues


def eligible_references(
    references: list[dict], *, as_of: str, scope: str
) -> list[dict]:
    """Only return references that can support an audit on the supplied date."""
    _context(as_of, scope)
    if not isinstance(references, list):
        raise TypeError("References must be a list.")
    identifiers = [
        reference["id"]
        for reference in references
        if isinstance(reference, dict) and isinstance(reference.get("id"), str)
    ]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Reference IDs must be unique.")
    return [
        reference
        for reference in references
        if not reference_issues(reference, as_of=as_of, scope=scope)
    ]


def reference_passages(
    references: list[dict], *, scope: str | None = None
) -> list[dict]:
    """Build passages without treating their retrieval as approval."""
    if not isinstance(references, list):
        raise TypeError("References must be a list.")
    if scope is not None and not _valid_scope(scope):
        raise ValueError("scope must be a nonempty, trimmed string.")
    passages = []
    for reference in references:
        if not _has_text_fields(
            reference, ("id", "version", "section_id", "text")
        ) or reference["version"] != reference_version(reference):
            raise ValueError("Reference passage has invalid content or version.")
        if scope is not None:
            if any(
                not _text_list(reference.get(field))
                for field in ("scope", "exclusions")
            ):
                raise ValueError("Reference scope and exclusions must be text lists.")
            if scope not in reference["scope"] or scope in reference["exclusions"]:
                continue
        passages.append(
            {
                "id": reference["id"],
                "text": reference["text"],
                "citation": {
                    "kind": "reference",
                    "reference_id": reference["id"],
                    "reference_version": reference["version"],
                    "section_id": reference["section_id"],
                    "quote": reference["text"],
                },
            }
        )
        if "interpretation_limits" in reference:
            limits = reference["interpretation_limits"]
            if not _text_list(limits):
                raise ValueError("Reference interpretation limits must be a text list.")
            passages[-1]["interpretation_limits"] = list(limits)
    return passages


def search_passages(query: str, passages: list[dict], limit: int = 3) -> list[dict]:
    """Require a majority of query terms, then rank overlap with stable ID ties."""
    if not isinstance(query, str):
        raise TypeError("Search query must be text.")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 3:
        raise ValueError("Search limit must be between one and three.")
    if not isinstance(passages, list):
        raise TypeError("Passages must be a list.")
    query_tokens = set(re.findall(r"[^\W_]+", query.casefold())) - STOP_WORDS
    ranked = []
    seen = set()
    for passage in passages:
        if not _has_text_fields(passage, ("id", "text")):
            raise ValueError("Each search passage needs a nonempty ID and text.")
        if passage["id"] in seen:
            raise ValueError("Search passage IDs must be unique.")
        seen.add(passage["id"])
        tokens = set(re.findall(r"[^\W_]+", passage["text"].casefold())) - STOP_WORDS
        overlap = len(query_tokens & tokens)
        if overlap > len(query_tokens) // 2:
            ranked.append((-overlap, passage["id"], passage))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [passage for _, _, passage in ranked[:limit]]
