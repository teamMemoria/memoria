"""Verify the exact policy answer and independent source for a draft."""

from backend.entities.guidelines import GUIDELINE_URL, GUIDELINES

SOURCE_PREFIX = "layer2-"
FAQ_KEY = SOURCE_PREFIX + "product-faq-search"
FAQ_ANSWER = "Open Search FAQ for a product question covered by the FAQ."
FAQ_QUOTE = "When you realize that the customer is asking something that can be found in the FAQ, click the [Search FAQ] button"
FAQ_URL = GUIDELINE_URL + "#L509-L548"
EXTENSION_KEY = SOURCE_PREFIX + "subscription-extension-refusal"
GOLD_EXTENSION_KEY = SOURCE_PREFIX + "subscription-gold-extension"
EXTENSION_ANSWER = (
    "For a subscription extension request, pull up the account, start the identity lookup "
    "and establish the membership tier. Bronze and Guest members do not qualify for a "
    "standard extension. Explain the refusal and ask whether the customer needs anything else."
)
EXTENSION_QUOTES = (
    "Get Full Name or Account ID for [Pull up Account]",
    "Start by looking up the order using the [Verify Identity] fields.",
    "Bronze and Guest members cannot get an extension > For these, apologize that you cannot do anything for them.",
    "Wrap up as usual.",
)
GOLD_EXTENSION_ANSWER = (
    "Gold members are eligible for a subscription extension. Pull up the account, start the "
    "identity lookup and record the membership tier before updating the eligible account. "
    "This guideline does not specify the length of the extension."
)
GOLD_EXTENSION_QUOTES = (
    *EXTENSION_QUOTES[:2],
    "Gold members can always get an extension",
    "Enter 'extend subscription' into [Update Account]",
)
EXTENSION_URL = GUIDELINE_URL + "#L487-L495"

_VERIFICATION_SOURCES = {
    **{
        key: (guideline.answer, guideline.quote, GUIDELINE_URL)
        for key, guideline in GUIDELINES.items()
    },
    FAQ_KEY: (FAQ_ANSWER, FAQ_QUOTE, FAQ_URL),
    EXTENSION_KEY: (EXTENSION_ANSWER, EXTENSION_QUOTES, EXTENSION_URL),
    GOLD_EXTENSION_KEY: (GOLD_EXTENSION_ANSWER, GOLD_EXTENSION_QUOTES, EXTENSION_URL),
}


def verification_source(key: str | None, answer: str):
    """Return the authoritative source for this exact draft, if one is known."""
    source = _VERIFICATION_SOURCES.get(key or "")
    return source if source and source[0] == answer else None


def matches_verification(key, answer, quote, url):
    source = verification_source(key, answer)
    if source is None:
        return False
    _, expected_quote, expected_url = source
    actual_quote = quote.strip()
    if isinstance(expected_quote, tuple):
        return (
            url == expected_url and tuple(actual_quote.splitlines()) == expected_quote
        )
    return url == expected_url and actual_quote == expected_quote
