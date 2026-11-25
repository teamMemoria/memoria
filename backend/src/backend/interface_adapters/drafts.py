"""Map #169's candidate groups to the existing pending draft contract."""

from itertools import combinations

from ml.versions import digest

from backend.entities.draft_matches import (
    account_lookup,
    faq_search,
    promo_exchange,
)
from backend.entities.guidelines import GUIDELINES, PROMO_AGE
from backend.entities.inferred_knowledge import Claim, Settings, learn
from backend.entities.policies import (
    EXTENSION_ANSWER,
    EXTENSION_KEY,
    FAQ_ANSWER,
    FAQ_KEY,
    GOLD_EXTENSION_ANSWER,
    GOLD_EXTENSION_KEY,
    PROMO_PREFIX,
    VERIFIED_PROMO_KEY,
)
from backend.interface_adapters.draft_examples import event, examples

EXTENSION_REQUEST = (
    r"\b(?:(?:(?:can|could|may) i|wondering if i (?:can|could)) (?:get|have|request)"
    r"|i (?:want|need|would like)(?: to request)?)"
    r" (?:an? )?extension (?:on|for|to|of) (?:my|the) (?:premium )?subscription\b"
    r"|\b(?:(?:can|could|would) you (?:please )?|i (?:want|need|would like) to )"
    r"extend (?:my|the) (?:premium )?subscription\b"
)


def _passage(conversation, turn):
    return {
        "source_key": f"ABCD:{conversation['id']}",
        "source_version": conversation["transcript_version"],
        "turn_id": f"ABCD:{conversation['id']}#t{turn['turn_id']}",
        "speaker": "system_action" if turn["speaker"] == "action" else turn["speaker"],
        "span": [0, len(turn["text"])],
        "quote": turn["text"],
    }


def _pending_draft(organization, key):
    return {
        "draft_id": key,
        "kind": "knowledge_draft",
        "status": "draft",
        "trusted": False,
        "audit_eligible": False,
        "company_id": organization,
    }


def draft_candidates(organization, conversations, settings: Settings, questions=()):
    exchanges = {}
    claims = []
    for conversation in conversations:
        match = promo_exchange(conversation["events"])
        if match is None:
            continue
        question, answer, days = match
        identifier = conversation["id"]
        exchanges[identifier] = (days, conversation, question, answer)
        claims.append(
            Claim(
                identifier,
                ("pricing", (), "days"),
                str(days),
                frozenset({"standard", "promo", "code", "expiry"}),
            )
        )

    drafts, conflicts = [], []
    for topic in learn(claims, settings):
        outcome = topic.decide(settings)
        if outcome == "undecided":
            continue
        # Even a minority alternate value needs visibility before approval.
        votes = topic.votes()
        for value, support in votes:
            key = PROMO_PREFIX + value
            verified = key == VERIFIED_PROMO_KEY
            evidence = [
                (conv, question, answer)
                for days, conv, question, answer in exchanges.values()
                if str(days) == value and conv["id"] in topic.values_by_call
            ]
            drafts.append(
                {
                    **_pending_draft(organization, key),
                    "topic": "Standard promo code expiry",
                    "question": "How long are standard promo codes valid?",
                    "answer": GUIDELINES[PROMO_AGE].answer
                    if verified
                    else f"Standard promo codes expire after {value} days.",
                    **(
                        {"agreement": (support, len(topic.values_by_call))}
                        if outcome == "candidate" and value == votes[0][0]
                        else {}
                    ),
                    "question_passages": [_passage(c, q) for c, q, _ in evidence],
                    "answer_passages": [_passage(c, a) for c, _, a in evidence],
                }
            )
    for left, right in combinations(drafts, 2):
        draft_ids = sorted((left["draft_id"], right["draft_id"]))
        conflicts.append(
            {
                "conflict_id": "-".join(draft_ids),
                "kind": "value",
                "status": "possible_conflict",
                "explanation": "Calls give different expiry periods for standard promo codes.",
                "a": {"type": "draft", "draft_id": left["draft_id"]},
                "b": {"type": "draft", "draft_id": right["draft_id"]},
            }
        )
    faq = _faq_draft(organization, conversations, settings)
    if faq is not None:
        drafts.append(faq)
    drafts.extend(_extension_drafts(organization, conversations, settings))
    drafts.extend(_scoped_drafts(organization, conversations))
    drafts.extend(
        _recurring_questions(organization, conversations, questions, settings)
    )
    return {
        "schema": "knowledge-pipeline/1",
        "status": "ok",
        "company_id": organization,
        "release_checks": {"release_allowed": True},
        "drafts": drafts,
        "conflicts": {"possible_conflicts": conflicts},
    }


def _recurring_questions(organization, conversations, questions, settings):
    """Stage observed answers; their frequency cannot establish a Layer 1 policy."""
    by_id = {str(c["id"]): c for c in conversations}
    for candidate in questions:
        pairs = {}
        for occurrence in candidate["occurrences"]:
            cid = str(occurrence["abcd_id"])
            conversation = by_id.get(cid)
            if (
                not conversation
                or occurrence["source_version"] != conversation["transcript_version"]
            ):
                continue
            events = {t["turn_id"]: t for t in conversation["events"]}
            selected = []
            for turn_id, speaker, quote in occurrence["observations"]:
                turn = events.get(turn_id)
                if turn and speaker == turn["speaker"] and quote == turn["text"]:
                    selected.append(turn)
            customer = [t for t in selected if t["speaker"] == "customer"]
            if not customer:
                continue
            question_turn = customer[0]["turn_id"]
            answers = [
                t
                for t in selected
                if t["speaker"] == "agent" and t["turn_id"] > question_turn
            ]
            if answers:
                pairs[cid] = (conversation, customer, answers)
        if len(pairs) < max(2, settings.min_calls):
            continue
        question = candidate["question"]
        key = digest(
            [candidate["category"], " ".join(question.casefold().rstrip(" ?").split())]
        )
        yield {
            **_pending_draft(
                organization, f"layer2-question-{key.removeprefix('sha256:')}"
            ),
            "topic": candidate["category"],
            "question": question,
            "answer": "Pending source verification. Review the observed replies and attach the applicable published answer.",
            "question_passages": [
                _passage(c, t) for c, turns, _ in pairs.values() for t in turns
            ],
            "answer_passages": [
                _passage(c, t) for c, _, turns in pairs.values() for t in turns
            ],
        }


def _faq_draft(organization, conversations, settings):
    evidence = {}
    for conversation in conversations:
        if match := faq_search(conversation["events"]):
            evidence[conversation["id"]] = [
                _passage(conversation, turn) for turn in match[:2]
            ]
    claims = [
        Claim(identifier, ("product", (), "procedure"), "search", frozenset({"faq"}))
        for identifier in evidence
    ]
    if not any(
        topic.decide(settings) == "candidate" for topic in learn(claims, settings)
    ):
        return None
    return {
        **_pending_draft(organization, FAQ_KEY),
        "topic": "Product information and care",
        "question": "When should an Agent open Search FAQ for a product question?",
        "answer": FAQ_ANSWER,
        "answer_passages": [passage for pair in evidence.values() for passage in pair],
    }


def _extension_drafts(organization, conversations, settings):
    evidence = {}
    for conversation in conversations:
        events = conversation["events"]
        request = event(events, "customer", EXTENSION_REQUEST)
        if request and (action := account_lookup(events, after=request["turn_id"])):
            evidence[conversation["id"]] = _passage(conversation, action)
    claims = [
        Claim(
            identifier, ("account", (), "procedure"), "lookup", frozenset({"account"})
        )
        for identifier in evidence
    ]
    if not any(
        topic.decide(settings) == "candidate" for topic in learn(claims, settings)
    ):
        return []
    return [
        {
            **_pending_draft(organization, key),
            "topic": "Subscriptions and membership",
            "question": question,
            "answer": answer,
            "answer_passages": list(evidence.values()),
        }
        for key, question, answer in (
            (
                EXTENSION_KEY,
                "How should an Agent handle an ineligible subscription extension?",
                EXTENSION_ANSWER,
            ),
            (
                GOLD_EXTENSION_KEY,
                "How should an Agent handle an eligible Gold subscription extension?",
                GOLD_EXTENSION_ANSWER,
            ),
        )
    ]


def _scoped_drafts(organization, conversations):
    for key, (conversation, question, reply) in examples(conversations):
        guideline = GUIDELINES[key]
        yield {
            **_pending_draft(organization, key),
            "topic": guideline.title,
            "question": guideline.question,
            "answer": guideline.answer,
            "question_passages": [_passage(conversation, question)],
            "answer_passages": [_passage(conversation, reply)],
        }
