"""Finite factual equivalents; no retrieval, approval or conversational inference."""

import re
from decimal import Decimal

from .rule_links import normal

QUANTITY = re.compile(
    r"(?P<currency>[$€£])\s*(?P<money>\d+(?:\.\d+)?)|(?P<count>\d+(?:\.\d+)?)\s*(?P<unit>business days?|days?|weeks?|hours?|percent|%)\b"
)
NUMBER_WORDS = dict(
    zip(
        (
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
        ),
        range(13),
        strict=True,
    )
)


def nonfactual_phrase(text):
    return bool(
        re.fullmatch(
            r"(?:sounds|that's|that is) (?:great|good|fine|okay)|great|excellent|okay|ok|"
            r"(?:thanks|thank you)(?: for (?:waiting|your patience|the information))?|"
            r"(?:hi|hello|bye|goodbye)|have a (?:good|nice|great) day",
            normal(text).strip(" .!?"),
        )
    )


def assertion_clause(text):
    """Only separate clear clauses; other fragments may qualify a nearby claim."""
    text = normal(text)
    if len(claim_atoms(text)) > 1:
        return True
    if re.match(
        r"(?:for|under|depending|when|while|where|whether|with|without|as|given|in case|on condition)\b",
        text,
    ):
        return False
    verb = re.search(
        r"\b(?:is|are|was|were|has|have|will|can|cannot|costs?|takes?|gets?|requires?|qualif(?:y|ies)|offers?|provides?)\b"
        r"|^(?:i|we|you|they|it|there)'(?:ll|ve|re|s)\b",
        text,
    )
    return bool(
        verb
        and not re.search(
            r"\b(?:that|which|whose|who|where|when|what)\b", text[: verb.start()]
        )
    )


def claim_frame(text):
    """Literal fallback retains every subject, unit and qualification."""
    values = []

    def replace(match):
        unit = match["currency"] or match["unit"].removesuffix("s")
        values.append((unit, Decimal(match["money"] or match["count"])))
        return "{" + unit + "}"

    canonical = normal(text).strip(" .!")
    return QUANTITY.sub(replace, canonical), values


def fact_frame(text):
    text = normal(text).strip(" .!")
    money = r"([$€£])\s*(\d+(?:\.\d+)?)"
    shipping = re.fullmatch(
        r"(?:the (?:cost|price) of (standard|overnight) shipping is "
        + money
        + r"|(standard|overnight) shipping (?:is|costs) "
        + money
        + r")",
        text,
    )
    if shipping:
        service, currency, value = (
            shipping.groups()[:3] if shipping[1] else shipping.groups()[3:]
        )
        return f"shipping-price:{service}:{currency}", [(currency, Decimal(value))]
    returns = re.fullmatch(
        r"(gold|silver|bronze|guest) members (?:get|have|are allowed|are entitled to) unlimited returns",
        text,
    )
    if returns:
        return "unlimited-returns:" + returns[1], []
    extension = re.fullmatch(
        r"(gold|silver|bronze|guest) members (?:(can)( always)? get|are( always)? eligible for|qualify for) an extension",
        text,
    )
    if extension:
        strength = "always" if extension[3] or extension[4] else "eligible"
        return "extension:" + extension[1], [("entitlement", strength)]
    # Only number words immediately attached to a declared unit are equivalents.
    # No currency conversion, date inference or business/calendar-day conversion.
    text = re.sub(
        r"\b("
        + "|".join(NUMBER_WORDS)
        + r")(?= (?:business )?(?:days?|weeks?|hours?|percent)\b)",
        lambda match: str(NUMBER_WORDS[match[1]]),
        text,
    )
    return claim_frame(text)


def compare_facts(reference, claim):
    expected, actual = fact_frame(reference), fact_frame(claim)
    if expected[0] != actual[0]:
        return None
    if expected[1] == actual[1]:
        return "supported"
    if expected[0].startswith("extension:"):
        if expected[1] == [("entitlement", "always")] and actual[1] == [
            ("entitlement", "eligible")
        ]:
            return "supported"
        return None
    # Frames retain units and conditions; only different numeric values deduct.
    if (
        expected[1]
        and len(expected[1]) == len(actual[1])
        and [unit for unit, _ in expected[1]] == [unit for unit, _ in actual[1]]
        and all(isinstance(value, Decimal) for _, value in expected[1] + actual[1])
    ):
        return "breach"
    return None


def claim_atoms(text):
    """Separate an explicit conditional benefit from unsupported personal facts."""
    value = normal(text).strip(" .!")
    returns = re.fullmatch(
        r"as (?:a |one of our (?:valued )?)(gold|silver|bronze|guest) members?,? "
        r"you (?:get|have|are allowed) (unlimited|unlimted) returns",
        value,
    )
    if returns:
        return [
            (returns[1] + " members get unlimited returns", None),
            (
                text,
                "The stated tier-conditioned return benefit is compared with policy. Actual membership, transaction eligibility and completion remain unresolved.",
            ),
        ]
    personal = re.fullmatch(
        r"as (?:a |one of our (?:valued )?)(gold|silver|bronze|guest) members?,? "
        r"(?:you qualify for|we're able to give you) an extension"
        r"(?: on your membership| which i have just put into place)?",
        value,
    )
    if personal:
        return [
            (personal[1] + " members are eligible for an extension", None),
            (
                text,
                "Only the explicitly stated tier-conditioned benefit is compared with policy. The customer's actual tier, personal eligibility and transaction completion remain unresolved.",
            ),
        ]
    return [(text, None)]
