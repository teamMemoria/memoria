"""Pure draft catalogue validation from metrics-scoring."""

import re
from copy import deepcopy

from ml.entities import CATEGORIES
from ml.versions import digest
from ml.wording import quotation_context

METRICS = ("procedure", "completeness", "communication-style", "answer-support")
DEFAULT_WEIGHT_PROFILE = "ordinary-support-draft-1"


def expand_common(common):
    """Restore shared fields before hashing the catalogue or preparing a review."""
    if "check_defaults" not in common:
        return common
    expanded = deepcopy(common)
    defaults = expanded.pop("check_defaults")
    for rule, template in expanded["check_templates"].items():
        fields = deepcopy(defaults)
        for key, value in template.items():
            if isinstance(fields.get(key), dict):
                fields[key].update(value)
            else:
                fields[key] = value
        expanded["check_templates"][rule] = fields
    if "metrics" not in expanded:
        expanded["metrics"] = {
            metric: {"parts": [], "maximum_points": 100} for metric in METRICS
        }
        for rule, template in expanded["check_templates"].items():
            expanded["metrics"][template["metric"]]["parts"].append(rule)
    return expanded


def category_entries(index):
    if "categories" in index:
        return index["categories"]
    names = index["category_order"]
    if any(not re.fullmatch(r"[a-z-]+", name) for name in names):
        raise ValueError("Invalid category catalogue ID")
    return [{"id": name, "file": f"{name}.json"} for name in names]


def _validate_weights(weights):
    if (
        not isinstance(weights, dict)
        or set(weights) != set(METRICS)
        or any(
            type(value) is not int or not 0 <= value <= 100
            for value in weights.values()
        )
        or sum(weights.values()) != 100
    ):
        raise ValueError("Metric weights must be four whole percentages totaling 100")


def expand_category(common, defaults, category):
    """Restore the versioned category schema from shared metric and condition defaults."""
    common = expand_common(common)
    conditions = category["check_conditions"]
    groups = common["metrics"]
    keys = groups.keys() | common["check_templates"].keys()
    if conditions.keys() - keys:
        raise ValueError("Unknown category condition")

    expanded = deepcopy(defaults)
    expanded.update(
        {
            key: value
            for key, value in category.items()
            if key not in {"check_conditions", "additional_interpretation_limits"}
        }
    )
    if additional := category.get("additional_interpretation_limits"):
        expanded["interpretation_limits"] = [
            *expanded["interpretation_limits"],
            *additional,
        ]
    expanded["metrics"] = {}
    for metric, group in groups.items():
        checks = []
        for part in group["parts"]:
            condition = conditions.get(part, conditions.get(metric))
            if not isinstance(condition, str) or not condition.strip():
                raise ValueError(f"Missing category condition for {part}")
            checks.append(
                {
                    "id": f"{expanded['id']}.{part}",
                    "template": part,
                    "category_condition": condition,
                }
            )
        expanded["metrics"][metric] = {
            "maximum_points": group["maximum_points"],
            "checks": checks,
        }
    return expanded


def catalogue(common, categories, *, weight_profile_id=DEFAULT_WEIGHT_PROFILE):
    """Reject invalid configuration rather than activate drafts implicitly."""
    if set(METRICS) != set(CATEGORIES):
        raise ValueError("Metric vocabulary differs from the shared categories")
    common = expand_common(common)
    categories = deepcopy(categories)
    templates = common["check_templates"]
    found = set()
    for category in categories:
        if category["id"] in found or set(category["metrics"]) != set(METRICS):
            raise ValueError("Duplicate category or unsupported metrics")
        found.add(category["id"])
        _validate_weights(category.get("weights"))
        for metric, group in category["metrics"].items():
            checks = group["checks"]
            expected = {k for k, t in templates.items() if t["metric"] == metric}
            if len({c["template"] for c in checks}) != len(checks):
                raise ValueError("Duplicate check template")
            if not checks or {c["template"] for c in checks} != expected:
                raise ValueError("Every metric must retain its configured checks")
            for check in checks:
                shared = templates[check["template"]]["part_points"]
                points = check.get("points", shared)
                if (
                    type(shared) is not int
                    or not 0 < shared <= 100
                    or type(points) is not int
                    or points != shared
                ):
                    raise ValueError("Invalid check or point allocation")
                check["points"] = shared
            if sum(c["points"] for c in checks) != 100:
                raise ValueError("Each metric requires 100 allocated points")
    if not {"general", "unclear"} <= found:
        raise ValueError("General and unclear categories are required")
    profiles = [p for p in common["weight_profiles"] if p["id"] == weight_profile_id]
    if len(profiles) != 1:
        raise ValueError("Select exactly one known weight profile by ID")
    profile = deepcopy(profiles[0])
    profile["version"] = digest(profiles[0])
    _validate_weights(profile["weights"])
    return {
        "common": deepcopy(common),
        "categories": categories,
        "weight_profile": profile,
        # Transcript reviews depend on the checks, not the later aggregation.
        "version": digest(
            [
                common,
                [
                    {key: value for key, value in category.items() if key != "weights"}
                    for category in categories
                ],
            ]
        ),
    }


def faq_question(events, opened, item):
    """Bind product questions to an explicit customer subject before the FAQ search."""
    subject = evidence = None
    item = item.removesuffix("s")
    for index, turn in enumerate(events):
        if turn["turn_id"] >= opened["turn_id"]:
            break
        if turn["speaker"] != "customer":
            continue
        text = turn["text"].casefold().replace("’", "'")
        if any(mark in text for mark in '"“”') or quotation_context(events, index):
            continue
        products = {
            match.removesuffix("s")
            for match in re.findall(r"\b(?:boots?|jeans|shirts?|jackets?)\b", text)
        }
        if products - {item} or re.search(
            r"\b(?:never mind|forget (?:it|that)|no longer|not asking)\b", text
        ):
            subject = evidence = None
            continue
        if (
            products == {item}
            and "?" in text
            and re.search(
                r"\b(?:stains?|wash|care|warranty|materials?|colou?r|waterproof|fit|stock|hood)\b|\bmade (?:of|from)\b",
                text,
            )
        ):
            evidence = [turn]
            subject = turn
        elif products == {item} and re.search(
            r"\b(?:i'd like|i would like|i need|i want) (?:some )?information about\b",
            text,
        ):
            subject = turn
        elif (
            not products
            and subject is not None
            and re.search(
                r"\bwhat (?:they are|it is|are they|is it) made (?:of|from)\b",
                text,
            )
        ):
            evidence = [subject, turn]
    return evidence
