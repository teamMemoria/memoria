"""Lexical attribution of quoted or repeated wording."""

import re


def quotation_context(events: list[dict], position: int) -> list[dict]:
    """Return explicit repetition cues or a same-speaker report span.

    Matching attribution markers close the nearest report; outer reports remain active.
    Another speaker ends the block, while an unclosed report leaves its remaining
    messages uncertain. Recorded actions do not change speaking ownership.
    """

    def normal(text):
        return " ".join(text.casefold().replace("’", "'").split()).rstrip(".!?")

    def party(text):
        match = re.search(r"\b(customer|caller|agent|representative)\b", normal(text))
        if match is None:
            return "unspecified"
        return "customer" if match[1] in ("customer", "caller") else "agent"

    def opens(text):
        match = re.fullmatch(
            r"(?:the (?:customer|caller|agent|representative) (?:said|wrote)|they said|i quote|the (?:customer|agent)'s words were):",
            normal(text),
        )
        return party(text) if match else None

    def closes(text):
        match = re.fullmatch(
            r"(?:those were the (?:customer|caller|agent|representative)'s words|that is what the (?:customer|caller|agent|representative) said|i was quoting the (?:customer|caller|agent|representative))",
            normal(text),
        )
        return party(text) if match else None

    speaker = events[position]["speaker"]
    if speaker not in ("agent", "customer"):
        return []
    messages = [
        index for index, event in enumerate(events) if event["speaker"] != "action"
    ]
    current = messages.index(position)
    previous = events[messages[current - 1]] if current else None
    following = events[messages[current + 1]] if current + 1 < len(messages) else None
    cues = []
    if previous is not None:
        repetition = re.fullmatch(
            r"(?:please|can you) (?:repeat|quote|say) (?:the |this )?(?:phrase|words|sentence)[: ]+(.+)",
            normal(previous["text"]),
        )
        if previous["speaker"] != speaker and repetition:
            requested = normal(normal(repetition[1]).strip("\"'“”‘’"))
            if requested == normal(events[position]["text"]):
                cues.append(previous)
        if previous["speaker"] == speaker and opens(previous["text"]):
            cues.append(previous)
    if (
        following is not None
        and following["speaker"] == speaker
        and closes(following["text"])
    ):
        cues.append(following)

    stack = []
    for index in messages[:current]:
        event = events[index]
        if event["speaker"] != speaker:
            stack.clear()
            continue
        opening = opens(event["text"])
        closing = closes(event["text"])
        if opening:
            stack.append((event, opening))
        elif closing and stack and stack[-1][1] in ("unspecified", closing):
            stack.pop()
    if stack:
        enclosing = [event for event, _ in stack]
        cues.extend(enclosing)
        for index in messages[current + 1 :]:
            event = events[index]
            if event["speaker"] != speaker:
                break
            opening = opens(event["text"])
            closing = closes(event["text"])
            if opening:
                stack.append((event, opening))
            elif closing and stack[-1][1] in ("unspecified", closing):
                if stack.pop()[0] in enclosing:
                    cues.append(event)
                if not stack:
                    break
    return [event for event in events if event in cues]
