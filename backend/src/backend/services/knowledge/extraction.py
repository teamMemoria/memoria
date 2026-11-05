"""Turn useful conversation answers into knowledge drafts with exact sources (#16).

``extract_drafts`` is the entry point. It takes one ABCD conversation (curated
or raw JSON) and returns an :class:`ExtractionResult`:

* ``status == "ok"`` with zero or more drafts. Zero drafts always comes with a
  ``no_draft_reason``, so "nothing reusable here" is never confused with a
  failure.
* ``status == "error"`` with ``errors``, for invalid or oversized input and for
  model failures. Nothing else is returned in that case.

Every draft links to the exact passages it came from (conversation id, turn
ids, character span and the quoted text after personal details are removed).
Drafts are always ``status: "draft"``, ``trusted: false`` and
``audit_eligible: false``: observing an answer in a conversation does not
verify it. Approval belongs to an authorized human through the backend.

Two extractors are provided:

* :class:`RuleExtractor` -- deterministic, no model, quotes only what was said.
* :class:`ModelExtractor` -- asks a :class:`~.llm.ModelClient` to pick the
  question, answer and condition turns, then checks the reply: unknown turn
  ids, invented figures, unsupported wording or personal data reject the
  draft instead of passing it through.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import text as tx
from .abcd import Conversation, read_conversation
from .errors import INTERNAL_ERROR, MODEL_OUTPUT_INVALID, PipelineError, invalid
from .llm import ModelClient
from .privacy import Redactor, placeholder_share

EXTRACTION_SCHEMA_VERSION = "knowledge-draft/1"

# Recorded actions that change something for the customer (as opposed to
# looking something up). An answer may cite these when the agent said little.
OUTCOME_ACTIONS = frozenset(
    {
        "promo-code",
        "offer-refund",
        "make-password",
        "send-link",
        "update-account",
        "update-order",
        "make-purchase",
        "notify-team",
    }
)
CONDITION_ACTIONS = frozenset({"membership"})

_GREETING = re.compile(
    r"^(hi|hello|hey|good (morning|afternoon|evening|day))\b|how (can|may|might) i (help|assist)"
    r"|thank(s| you)( so much| very much)? for\b|\bi thank you\b|\bappreciate you\b"
    r"|\banything else\b|\bhave an? (\w+ )?(day|night|evening|weekend|one)\b|\b(take care|goodbye|bye)\b"
    r"|you('| a)?re (very )?welcome|\benjoy (the|your)\b|\bend (this|the) (chat|conversation)\b|^welcome to"
    r"|\bglad (i|we) could help\b|\bglad to hear\b|\bpleasure to help\b|\bstay (safe|well)\b|\bbe safe\b"
    r"|\bdisconnected\b|\bhope (you|that) (have|get|can)\b",
    re.IGNORECASE,
)
_REQUEST = re.compile(
    r"\b(may|can|could|might) i (please )?(have|get|ask|grab|know|see|confirm|verify)\b"
    r"|\b(can|could|would) you (please )?(tell|provide|give|send|confirm|verify|spell|share|re-?enter)\b"
    r"|\bwhat (is|are|was) (your|the) (correct |old |new )?(full name|name|account|email|username|order|zip|phone|membership|address)"
    r"|\bwhat (is|was) (your|the) (correct|old|new)\b"
    r"|\bplease (provide|send|confirm|enter|tell)\b"
    r"|\b(i|we)('ll| will)? (also |just |first )?need (\d|one|two|three|either|your|the|to (get|have|verify|validate|confirm))\b"
    r"|\b(i|we) need (\d|two|three) of\b|\b(\d|two|three) of (those|the|them|these)\b"
    r"|^(give|send|tell) me\b|\bneed to (validate|verify) (your|the)\b|\bthe first thing i need\b"
    r"|\bdo you (have|know|happen to)\b|\bwhich (item|product|one)\b|\blet me know\b",
    re.IGNORECASE,
)
_FILLER = re.compile(
    r"^(i'?m|i am) (so |very |really )?sorry\b|^i (completely |totally )?understand\b|^let me (just )?(check|see|look|pull|take|help|confirm)"
    r"|^(one|just a) (moment|second|sec|minute)|^give me a (moment|second|sec)|^(i'?d|i would|i'?ll|i will) be (happy|glad)"
    r"|^(i'?m|i am) (more than )?(happy|glad) to\b|^i('d| would) (love|be happy) to\b"
    r"|^(no problem|not a problem|great|okay|ok|alright|all right|perfect|awesome|sure|thanks|thank you|got it|excellent)\b[.!]*$"
    r"|^(i'?m|i am) (checking|looking|pulling|still working)\b|^(i'?m|i am) going to (check|look|pull|see)"
    r"|^(sure|yes|okay|ok)?,? ?i can (definitely |certainly )?(help|look|do that|assist)\b"
    r"|^(sure|ok|okay),? (thing|no worries)\b|\bthat'?s what we are here for\b"
    r"|^(and )?(would|will|i'?d|i would) (be )?(glad|happy) to (help|assist)\b",
    re.IGNORECASE,
)
_LEAD_IN = re.compile(
    r"^(?:(?:oh|ok|okay|well|so|yes|yep|alright|all right|great|indeed|perfect|thanks|thank you|sure|got it|no worries|i see|good news)\b[,.!-]?\s*)*"
    r"(?:(?:i'?m|i am|we'?re|we are)\s+(?:so |very |really |truly )?sorry(?: (?:about|for|to hear)[^,.!]*)?|i (?:do )?apologi[sz]e(?: for[^,.!]*)?|sorry(?: about that)?)?[,.!]?\s*",
    re.IGNORECASE,
)
_ACCOUNT_PROCESS = re.compile(
    r"\b(i can see your account|pull(ed|ing)? up your account|looking at (the|your) account|go into your account"
    r"|in our system now|check(ing)? (the|our) system|let me (go|get|grab|find|bring)|one moment"
    r"|^(but )?let'?s (see|take a look|figure|look|try)|clear (that|this) up|(any|of) (more|further) (assistance|help)"
    r"|could(n'?t| not) (be of|help)|^(i|we) hope (this|that) helps|located your account|same set of characters"
    r"|if i understand correctly|search up that information|look (in|up) (to|that|this|materials)|while i search)\b",
    re.IGNORECASE,
)
# "Your new password is [ACCOUNT_DETAIL]": hands one customer a value; not reusable.
_VALUE_HANDOFF = re.compile(
    r"(\bis|:|-)\s*\[[A-Z_]+\][.!]?\s*$|^\[(CODE|ACCOUNT_DETAIL|USERNAME)\]"
)
# A sentence carrying one customer's details ("Your order [ORDER_ID] arrives on
# [DATE]") is about that customer only. A name used to address them is fine.
_ACCOUNT_PLACEHOLDER = re.compile(
    r"\[(ORDER_ID|DATE|PURCHASE_DATE|ACCOUNT_DETAIL|CODE|USERNAME|NUMBER|PHONE|EMAIL|ADDRESS|CARD_NUMBER|ZIP_CODE|CITY)\]"
)
_IDENTITY = re.compile(
    r"\b(my name is|name'?s|account id|account number|username is|user name is|email is|zip( code)? is|phone( number)? is"
    r"|order id|order number|it'?s \[|i'?m \[CUSTOMER_NAME\])"
    r"|\b(username|user name|email( address)?|order id|account id|zip( code)?|phone( number)?)\s*:",
    re.IGNORECASE,
)
_OFFER = re.compile(
    r"^(would|do) you (like|want) (me|us) to\b|^(i|we) can\b|^if you('d| would)? like\b",
    re.IGNORECASE,
)
_IN_PROGRESS = re.compile(r"\.\.\.\s*$|\bin progress\b", re.IGNORECASE)
_NEED = re.compile(
    r"\b(help|need|want|tr(y|ies|ied|ying)|can'?t|cannot|won'?t|doesn'?t|isn'?t|problem|issue|forg[eo]t|lost|how|when|why"
    r"|what|where|wrong|return|refund|cancel|chang|updat|order|code|charg|fee|ship|deliver|stock|pric|member"
    r"|account|password|username|slow|work|search|bill|pay|status|curious|wonder|question|know|inquir|trouble"
    r"|disput|subscri|missing|late|broken|damag|stain|size|color|colour|policy|cost)",
    re.IGNORECASE,
)
# "To recover your username I will need your full name or account ID" states a
# requirement that applies to every customer, unlike "May I have your name?".
_REQUIREMENT = re.compile(
    r"\bto (recover|reset|verify|validate|change|process|return|refund|cancel|update|confirm|issue|make)\b.*\b(need|require)"
    r"|\b(\d|two|three|either) of the (\d|two|three|following)\b|\b(need|require)s? (either|both)\b",
    re.IGNORECASE,
)
_CONDITION = re.compile(
    r"\b(if|unless|only|as long as|provided|depending on|depends on|within|after|before|more than|less than"
    r"|at least|up to|over|under|except|must|have to|has to|need to|required?|requires|eligible|qualif(y|ies)"
    r"|valid|expire[sd]?|until|days?|weeks?|months?)\b|\b(gold|silver|bronze|guest)s?\b|\bmembers?\b",
    re.IGNORECASE,
)
_SELF_REPORTED_CONDITION = re.compile(
    r"\b(i'?m|i am|im)\s+(just\s+)?(a\s+)?(gold|silver|bronze|guest)\b|\bmember level:?\s*(gold|silver|bronze|guest)\b"
    r"|\b(gold|silver|bronze)\s+member\b|\bas a guest\b|\b(issued|got it|received it)\b.*\b\d+\s+days?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractionConfig:
    """Choices the team still has to agree (issue #16, "To agree"). Defaults are a starting point.

    ``topics``: ABCD flows or ``flow/subflow`` pairs to extract from; ``None`` means all.
    ``min_answer_words``: a sentence shorter than this is not treated as an answer.
    ``max_placeholder_share``: a sentence that is mostly removed personal data is not reusable.
    ``allow_action_only_answers``: whether an answer may consist only of recorded outcome actions.
    """

    topics: frozenset[str] | None = None
    min_answer_words: int = 5
    max_placeholder_share: float = 0.34
    allow_action_only_answers: bool = True
    max_drafts_per_conversation: int = 3

    def __post_init__(self) -> None:
        topics = self.topics
        if topics is not None and (
            isinstance(topics, str)
            or not isinstance(topics, frozenset | set | list | tuple)
            or not all(isinstance(t, str) and t for t in topics)
        ):
            raise invalid(
                "config.extraction.topics",
                "must be null or a list of flow or flow/subflow names",
            )
        if topics is not None and not topics:
            # An empty list would quietly select nothing; leave it out to select everything.
            raise invalid(
                "config.extraction.topics",
                "must not be empty; use null to select every topic",
            )
        if topics is not None and not isinstance(topics, frozenset):
            object.__setattr__(self, "topics", frozenset(topics))
        for name, low in (("min_answer_words", 1), ("max_drafts_per_conversation", 1)):
            value = getattr(self, name)
            if type(value) is not int or value < low:
                raise invalid(
                    f"config.extraction.{name}", f"must be an integer >= {low}"
                )
        share = self.max_placeholder_share
        if type(share) not in (int, float) or not 0 <= share <= 1:
            raise invalid(
                "config.extraction.max_placeholder_share",
                "must be a number between 0 and 1",
            )
        if type(self.allow_action_only_answers) is not bool:
            raise invalid(
                "config.extraction.allow_action_only_answers", "must be true or false"
            )

    def topic_selected(self, scope: Mapping[str, str]) -> bool:
        if self.topics is None:
            return True
        return (
            scope["flow"] in self.topics
            or f"{scope['flow']}/{scope['subflow']}" in self.topics
        )


@dataclass(frozen=True)
class Passage:
    """An exact, citable piece of a conversation, after personal details were removed."""

    conversation_id: str
    source_key: str
    turn_id: str
    speaker: str
    start: int
    end: int
    quote: str
    source_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "source_key": self.source_key,
            "turn_id": self.turn_id,
            "speaker": self.speaker,
            "span": [self.start, self.end],
            "quote": self.quote,
            "source_version": self.source_version,
        }


@dataclass
class RedactedConversation:
    conversation: Conversation
    texts: dict[str, str]
    redactions: Counter[str]
    redactor: Redactor

    def passage(self, turn_id: str, span: tuple[int, int] | None = None) -> Passage:
        turn = self.conversation.turn(turn_id)
        full = self.texts[turn_id]
        start, end = span if span else (0, len(full))
        return Passage(
            conversation_id=self.conversation.conversation_id,
            source_key=self.conversation.source_key,
            turn_id=turn_id,
            speaker=turn.speaker,
            start=start,
            end=end,
            quote=full[start:end],
            source_version=self.conversation.source["version"],
        )


def redact_conversation(conversation: Conversation) -> RedactedConversation:
    redactor = Redactor(conversation.customer_record)
    texts: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for turn in conversation.turns:
        result = redactor.redact(turn.text)
        texts[turn.turn_id] = result.text
        counts.update(result.counts)
    return RedactedConversation(conversation, texts, counts, redactor)


@dataclass(frozen=True)
class Condition:
    text: str
    basis: str  # agent_statement | customer_statement | recorded_action
    passage: Passage

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "basis": self.basis,
            "passage": self.passage.to_dict(),
        }


@dataclass(frozen=True)
class Selection:
    """What an extractor chose: the turns/spans that make up one draft."""

    question: tuple[Passage, ...]
    answer: tuple[Passage, ...]
    conditions: tuple[Condition, ...] = ()
    question_text: str | None = None  # model wording; None means the quotes themselves
    answer_text: str | None = None


@dataclass
class ExtractionResult:
    conversation_id: str | None
    source_key: str | None
    status: str
    drafts: list[dict[str, Any]] = field(default_factory=list)
    no_draft_reason: str | None = None
    rejected: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "source_key": self.source_key,
            "status": self.status,
            "drafts": self.drafts,
            "no_draft_reason": self.no_draft_reason,
            "rejected_drafts": self.rejected,
            "errors": self.errors,
        }


class Extractor(Protocol):
    name: str
    version: str

    def select(
        self, redacted: RedactedConversation, config: ExtractionConfig
    ) -> tuple[list[Selection], str | None, list[dict[str, Any]]]:
        """Return (selections, no-draft reason or None, rejected proposals)."""
        ...


# --------------------------------------------------------------------------- rule extractor


def _word_count(text: str) -> int:
    return len([w for w in tx.words(text) if not w.startswith("[")])


def _core(sentence: str) -> str:
    """The sentence without a leading interjection or apology ("Oh, I'm sorry, ...")."""
    return _LEAD_IN.sub("", sentence.strip(), count=1)


def _is_answer_sentence(sentence: str, config: ExtractionConfig) -> bool:
    stripped = _core(sentence)
    if (
        _ACCOUNT_PROCESS.search(stripped)
        or _VALUE_HANDOFF.search(stripped)
        or _ACCOUNT_PLACEHOLDER.search(stripped)
    ):
        return False
    if _word_count(stripped) < config.min_answer_words:
        return False
    if placeholder_share(stripped) > config.max_placeholder_share:
        return False
    if _GREETING.search(stripped) or _FILLER.search(stripped):
        return False
    if _REQUEST.search(stripped) and not _REQUIREMENT.search(stripped):
        return False
    # A question is only an answer when it offers something ("Would you like me to ...").
    return not stripped.endswith("?") or bool(_OFFER.search(stripped))


def _next_turn(conversation: Conversation, n: int):
    for turn in conversation.turns:
        if turn.n > n:
            return turn
    return None


def _question_turns(redacted: RedactedConversation, before_n: int) -> list[str]:
    conversation = redacted.conversation
    candidates = []
    for turn in conversation.turns:
        if turn.n >= before_n:
            break
        if turn.speaker != "customer":
            continue
        text = redacted.texts[turn.turn_id]
        if _word_count(text) < 4 or placeholder_share(text) > 0.25:
            continue
        if _IDENTITY.search(text) and _word_count(text) < 12:
            continue
        if not candidates and (_NEED.search(text) or text.rstrip().endswith("?")):
            candidates.append(turn.turn_id)
            # A short opener ("I hope someone can help") is usually followed by the
            # actual request in the next customer turn.
            following = _next_turn(conversation, turn.n)
            if (
                _word_count(text) < 8
                and following is not None
                and following.speaker == "customer"
                and following.n < before_n
                and not _IDENTITY.search(redacted.texts[following.turn_id])
                and placeholder_share(redacted.texts[following.turn_id]) <= 0.5
            ):
                candidates.append(following.turn_id)
        elif candidates and text.rstrip().endswith("?") and "[" not in text:
            candidates.append(turn.turn_id)
    return candidates[:2]


def _conditions(
    redacted: RedactedConversation, answer: Sequence[Passage], upto_n: int
) -> list[Condition]:
    found: list[Condition] = []
    seen: set[tuple[str, int, int]] = set()

    def add(passage: Passage, basis: str) -> None:
        key = (passage.turn_id, passage.start, passage.end)
        if key not in seen:
            seen.add(key)
            found.append(Condition(passage.quote, basis, passage))

    for passage in answer:
        core = _core(passage.quote)
        if passage.speaker == "agent" and (
            _CONDITION.search(core) or _REQUIREMENT.search(core)
        ):
            add(passage, "agent_statement")
    conversation = redacted.conversation
    for turn in conversation.turns:
        if turn.n > upto_n:
            break
        text = redacted.texts[turn.turn_id]
        hypothetical = re.search(r"\bif\s+(i'?m|i am|im)\b", text, re.IGNORECASE)
        if (
            turn.speaker == "customer"
            and _SELF_REPORTED_CONDITION.search(text)
            and not hypothetical
        ):
            add(redacted.passage(turn.turn_id), "customer_statement")
    for action in conversation.actions:
        if action.name in CONDITION_ACTIONS and action.turn_id:
            passage = redacted.passage(action.turn_id)
            if tx.membership_levels(passage.quote) and all(
                c.text != passage.quote for c in found
            ):
                add(passage, "recorded_action")
    return found


class RuleExtractor:
    """Deterministic extractor: quotes the customer's request and the agent's substantive answer."""

    name = "rule-extractor"
    version = "1"

    def select(
        self, redacted: RedactedConversation, config: ExtractionConfig
    ) -> tuple[list[Selection], str | None]:
        conversation = redacted.conversation
        answer: list[Passage] = []
        first_answer_n: int | None = None
        last_answer_n = 0
        for turn in conversation.turns:
            if turn.speaker != "agent":
                continue
            text = redacted.texts[turn.turn_id]
            for start, end in tx.sentences(text):
                if _is_answer_sentence(text[start:end], config):
                    answer.append(redacted.passage(turn.turn_id, (start, end)))
                    first_answer_n = first_answer_n or turn.n
                    last_answer_n = turn.n
        outcome = [
            redacted.passage(a.turn_id)
            for a in conversation.actions
            if a.name in OUTCOME_ACTIONS
            and a.turn_id
            and not _IN_PROGRESS.search(redacted.texts[a.turn_id])
            # A recorded action that carries this customer's details ("Account has
            # been updated with [ADDRESS]") says nothing reusable.
            and placeholder_share(redacted.texts[a.turn_id]) == 0
        ]
        if not answer:
            if not (config.allow_action_only_answers and outcome):
                return [], "no_reusable_answer", []
            answer = outcome
            first_answer_n = min(conversation.turn(p.turn_id).n for p in outcome)
            last_answer_n = max(conversation.turn(p.turn_id).n for p in outcome)
        else:
            # Keep outcome actions that happened while the agent was answering.
            for passage in outcome:
                n = conversation.turn(passage.turn_id).n
                if (
                    first_answer_n is not None
                    and first_answer_n <= n <= last_answer_n + 2
                ):
                    answer.append(passage)
            answer.sort(key=lambda p: (conversation.turn(p.turn_id).n, p.start))
        question_ids = _question_turns(redacted, first_answer_n or 10**9)
        if not question_ids:
            return [], "no_customer_request", []
        question = tuple(redacted.passage(turn_id) for turn_id in question_ids)
        conditions = _conditions(redacted, answer, last_answer_n)
        return (
            [
                Selection(
                    question=question,
                    answer=tuple(answer),
                    conditions=tuple(conditions),
                )
            ],
            None,
            [],
        )


# --------------------------------------------------------------------------- model extractor

MODEL_SYSTEM_PROMPT = """You extract reusable customer-support knowledge from one finished chat.
Personal details have already been replaced by placeholders such as [CUSTOMER_NAME]; keep them as they are.
Return JSON only, in this shape:
{"drafts": [{"question": str, "question_turn_ids": [str], "answer": str, "answer_turn_ids": [str],
  "conditions": [{"text": str, "turn_ids": [str]}]}], "no_draft_reason": str | null}
Rules:
- A draft is a question a future customer could ask and the answer the agent gave, with every condition
  (membership level, time limits, eligibility) that the answer depends on.
- Use only what the cited turns say. Do not add dates, amounts, names, outcomes or policies that are not in them.
- Cite every turn the question, answer and each condition rely on, using the given turn ids.
- If the chat contains nothing reusable (only account-specific steps, small talk, or no answer), return
  {"drafts": [], "no_draft_reason": "<short reason>"}.
"""

_MAX_MODEL_DRAFTS = 5


def _model_prompt(redacted: RedactedConversation) -> str:
    conversation = redacted.conversation
    lines = [
        f"topic: {conversation.scope['flow']}/{conversation.scope['subflow']}",
        "turns:",
    ]
    for turn in conversation.turns:
        lines.append(
            json.dumps(
                {
                    "turn_id": turn.turn_id,
                    "speaker": turn.speaker,
                    "text": redacted.texts[turn.turn_id],
                }
            )
        )
    return "\n".join(lines)


def _supported(
    statement: str, passages: Sequence[Passage], min_support: float
) -> str | None:
    """Return why ``statement`` is not supported by ``passages``, or None if it is."""
    source = " ".join(p.quote for p in passages)
    missing_numbers = tx.numbers(statement) - tx.numbers(source)
    if missing_numbers:
        return f"mentions figures not in its passages: {sorted(missing_numbers)}"
    extra_levels = tx.membership_levels(statement) - tx.membership_levels(source)
    if extra_levels:
        return f"mentions membership levels not in its passages: {sorted(extra_levels)}"
    if tx.is_negated(statement) and not tx.is_negated(source):
        return "is negative but its passages are not"
    terms = set(tx.content_terms(statement))
    if terms:
        support = len(terms & set(tx.content_terms(source))) / len(terms)
        if support < min_support:
            return f"only {support:.0%} of its content words appear in its passages"
    return None


@dataclass
class ModelExtractor:
    client: ModelClient
    min_support: float = 0.6
    max_output_tokens: int = 1_500
    name: str = "model-extractor"
    version: str = "1"

    def select(
        self, redacted: RedactedConversation, config: ExtractionConfig
    ) -> tuple[list[Selection], str | None, list[dict[str, Any]]]:
        reply = self.client.complete_json(
            system=MODEL_SYSTEM_PROMPT,
            prompt=_model_prompt(redacted),
            max_output_tokens=self.max_output_tokens,
        )
        if not isinstance(reply, Mapping):
            raise PipelineError(
                MODEL_OUTPUT_INVALID, "model reply is not a JSON object", "model"
            )
        rejected: list[dict[str, Any]] = []
        drafts = reply.get("drafts")
        if not isinstance(drafts, list):
            raise PipelineError(
                MODEL_OUTPUT_INVALID,
                "model reply has no 'drafts' array",
                "model.drafts",
            )
        if not drafts:
            reason = reply.get("no_draft_reason")
            if not isinstance(reason, str) or not reason.strip():
                raise PipelineError(
                    MODEL_OUTPUT_INVALID,
                    "model returned no drafts and no reason",
                    "model.no_draft_reason",
                )
            # The model's own words: remove personal details before they go anywhere.
            safe = redacted.redactor.redact(reason.strip()[:200]).text
            return [], f"model: {safe}", []
        if len(drafts) > _MAX_MODEL_DRAFTS:
            raise PipelineError(
                MODEL_OUTPUT_INVALID,
                f"model returned {len(drafts)} drafts",
                "model.drafts",
            )
        selections: list[Selection] = []
        for index, item in enumerate(drafts):
            try:
                selections.append(self._selection(redacted, item))
            except _Rejected as problem:
                rejected.append({"index": index, "reason": str(problem)})
        if not selections:
            return [], "model: every proposed draft was rejected", rejected
        return selections, None, rejected

    def _turns(
        self, redacted: RedactedConversation, ids: Any, what: str
    ) -> list[Passage]:
        if (
            not isinstance(ids, list)
            or not ids
            or not all(isinstance(i, str) for i in ids)
        ):
            raise _Rejected(f"{what} must cite at least one turn id")
        known = redacted.texts.keys()
        unknown = [i for i in ids if i not in known]
        if unknown:
            # Not echoed back: a made-up id could carry anything.
            raise _Rejected(f"{what} cites {len(unknown)} turn id(s) that do not exist")
        return [redacted.passage(i) for i in dict.fromkeys(ids)]

    def _selection(self, redacted: RedactedConversation, item: Any) -> Selection:
        if not isinstance(item, Mapping):
            raise _Rejected("draft is not an object")
        question = item.get("question")
        answer = item.get("answer")
        if (
            not isinstance(question, str)
            or not question.strip()
            or not isinstance(answer, str)
            or not answer.strip()
        ):
            raise _Rejected("question and answer must be non-empty strings")
        q_passages = self._turns(redacted, item.get("question_turn_ids"), "question")
        a_passages = self._turns(redacted, item.get("answer_turn_ids"), "answer")
        if not any(p.speaker == "customer" for p in q_passages):
            raise _Rejected("question must cite a customer turn")
        if not any(p.speaker in {"agent", "system_action"} for p in a_passages):
            raise _Rejected("answer must cite an agent or system_action turn")
        raw_conditions = item.get("conditions")
        if raw_conditions is None:
            raw_conditions = []
        if not isinstance(raw_conditions, list):
            raise _Rejected("conditions must be an array")
        wording = [question, answer] + [
            c.get("text", "") for c in raw_conditions if isinstance(c, Mapping)
        ]
        for statement in wording:
            if isinstance(statement, str) and (
                redacted.redactor.leaks(statement)
                or redacted.redactor.redact(statement).counts
            ):
                raise _Rejected("model wording contains personal details")
        for label, statement, passages in (
            ("question", question, q_passages),
            ("answer", answer, a_passages),
        ):
            problem = _supported(statement, passages, self.min_support)
            if problem:
                raise _Rejected(f"{label} {problem}")
        conditions = []
        for condition in raw_conditions:
            if not isinstance(condition, Mapping) or not isinstance(
                condition.get("text"), str
            ):
                raise _Rejected("each condition needs text and turn_ids")
            passages = self._turns(redacted, condition.get("turn_ids"), "condition")
            problem = _supported(condition["text"], passages, self.min_support)
            if problem:
                raise _Rejected(f"condition {problem}")
            basis = {"agent": "agent_statement", "customer": "customer_statement"}.get(
                passages[0].speaker, "recorded_action"
            )
            for passage in passages:
                conditions.append(Condition(condition["text"].strip(), basis, passage))
        return Selection(
            question=tuple(q_passages),
            answer=tuple(a_passages),
            conditions=tuple(conditions),
            question_text=question.strip(),
            answer_text=answer.strip(),
        )


class _Rejected(Exception):
    pass


# --------------------------------------------------------------------------- drafts


def _turn_number(turn_id: str) -> int:
    return int(turn_id.rsplit("#t", 1)[1])


def _draft_id(
    conversation: Conversation, extractor: Extractor, selection: Selection
) -> str:
    """Stable across reads: the same source conversation (curated or raw) and the
    same cited spans always give the same id. Model wording is part of it, so
    two different model drafts on the same turns stay apart."""
    key = json.dumps(
        [
            conversation.company_id,
            conversation.source_key,
            extractor.name,
            extractor.version,
            [(_turn_number(p.turn_id), p.start, p.end) for p in selection.question],
            [(_turn_number(p.turn_id), p.start, p.end) for p in selection.answer],
            selection.question_text,
            selection.answer_text,
        ]
    )
    return "draft_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _join(passages: Iterable[Passage]) -> str:
    return " ".join(p.quote.strip() for p in passages)


def build_draft(
    redacted: RedactedConversation, extractor: Extractor, selection: Selection
) -> dict[str, Any]:
    conversation = redacted.conversation
    cited = {p.turn_id for p in (*selection.question, *selection.answer)} | {
        c.passage.turn_id for c in selection.conditions
    }
    scope = {"company_id": conversation.company_id, **conversation.scope}
    return {
        "schema": EXTRACTION_SCHEMA_VERSION,
        "draft_id": _draft_id(conversation, extractor, selection),
        "kind": "knowledge_draft",
        "status": "draft",
        "trusted": False,
        "audit_eligible": False,
        "company_id": conversation.company_id,
        "scope": scope,
        "topic": f"{conversation.scope['flow']}/{conversation.scope['subflow']}",
        "question": selection.question_text or _join(selection.question),
        "answer": selection.answer_text or _join(selection.answer),
        "wording": "model" if selection.answer_text else "verbatim",
        "question_passages": [p.to_dict() for p in selection.question],
        "answer_passages": [p.to_dict() for p in selection.answer],
        "conditions": [c.to_dict() for c in selection.conditions],
        "procedure": [a.to_dict() for a in conversation.actions],
        "source": {
            "conversation_id": conversation.conversation_id,
            "source_key": conversation.source_key,
            **{
                k: conversation.source[k]
                for k in (
                    "dataset",
                    "original_id",
                    "version",
                    "dataset_version",
                    "split",
                    "licence",
                )
            },
        },
        "evidence_coverage": {
            **conversation.coverage,
            "turns_cited": len(cited),
            "cited_share": round(len(cited) / max(1, len(conversation.turns)), 4),
        },
        "privacy": {"redactions": dict(sorted(redacted.redactions.items()))},
        "extractor": {"name": extractor.name, "version": extractor.version},
        "verification": {
            "status": "not_verified",
            "note": "Observed in a conversation. Observing an answer does not verify it.",
        },
    }


def extract_drafts(
    record: Any,
    company_id: str,
    extractor: Extractor | None = None,
    config: ExtractionConfig | None = None,
) -> ExtractionResult:
    """Extract drafts from one ABCD record. Never raises for bad input; returns status "error"."""
    extractor = extractor or RuleExtractor()
    config = config or ExtractionConfig()
    try:
        conversation = (
            record
            if isinstance(record, Conversation)
            else read_conversation(record, company_id)
        )
    except PipelineError as error:
        return ExtractionResult(None, None, "error", errors=[error.to_dict()])
    if conversation.company_id != company_id:
        error = PipelineError(
            "invalid_input", "conversation belongs to another company", "company_id"
        )
        return ExtractionResult(
            conversation.conversation_id,
            conversation.source_key,
            "error",
            errors=[error.to_dict()],
        )
    result = ExtractionResult(
        conversation.conversation_id, conversation.source_key, "ok"
    )
    if not config.topic_selected(conversation.scope):
        result.no_draft_reason = "topic_not_selected"
        return result
    redacted = redact_conversation(conversation)
    try:
        selections, reason, rejected = extractor.select(redacted, config)
    except PipelineError as error:
        return ExtractionResult(
            conversation.conversation_id,
            conversation.source_key,
            "error",
            errors=[error.to_dict()],
        )
    except Exception as error:  # noqa: BLE001 - a bug must surface as an error, never as "no drafts"
        failure = PipelineError(
            INTERNAL_ERROR, f"extractor failed: {type(error).__name__}", "extractor"
        )
        return ExtractionResult(
            conversation.conversation_id,
            conversation.source_key,
            "error",
            errors=[failure.to_dict()],
        )
    result.rejected = rejected
    if not selections and rejected:
        # The model answered, but nothing it proposed could be used: a model
        # failure, not a conversation without reusable knowledge.
        failure = PipelineError(
            MODEL_OUTPUT_INVALID,
            f"every one of the {len(rejected)} proposed drafts was rejected",
            "model.drafts",
        )
        return ExtractionResult(
            conversation.conversation_id,
            conversation.source_key,
            "error",
            rejected=rejected,
            errors=[failure.to_dict()],
        )
    if not selections:
        result.no_draft_reason = reason or "no_reusable_answer"
        return result
    drafts: dict[str, dict[str, Any]] = {}
    for index, selection in enumerate(selections[: config.max_drafts_per_conversation]):
        draft = build_draft(redacted, extractor, selection)
        if draft["draft_id"] in drafts:
            result.rejected.append(
                {"index": index, "reason": "repeats an earlier draft exactly"}
            )
            continue
        drafts[draft["draft_id"]] = draft
    result.drafts = list(drafts.values())
    return result


def check_draft_citations(
    draft: Mapping[str, Any], conversation: Conversation
) -> list[str]:
    """Problems with a draft's citations against its conversation; [] when every quote is exact."""
    problems = []
    if draft.get("wording") not in ("verbatim", "model"):
        problems.append("draft has an unknown wording type")
    source = draft.get("source")
    if (
        not isinstance(source, Mapping)
        or source.get("version") != conversation.source["version"]
    ):
        problems.append("draft source version does not match")
    redacted = redact_conversation(conversation)
    passages = [*draft.get("question_passages", []), *draft.get("answer_passages", [])]
    passages += [c["passage"] for c in draft.get("conditions", [])]
    if not draft.get("question_passages") or not draft.get("answer_passages"):
        problems.append("draft has no question or no answer passage")
    for passage in passages:
        problems += check_passage(passage, conversation, redacted)
    if draft.get("wording") == "verbatim":
        # Verbatim wording is the quotes themselves; anything else was rewritten.
        for field_name, key in (
            ("question", "question_passages"),
            ("answer", "answer_passages"),
        ):
            quotes = " ".join(
                str(p.get("quote", "")).strip() for p in draft.get(key, [])
            )
            if draft.get(field_name) != quotes:
                problems.append(f"{field_name} is not the text of its passages")
        for condition in draft.get("conditions", []):
            if condition.get("text") != (condition.get("passage") or {}).get("quote"):
                problems.append("a condition is not the text of its passage")
    return problems


def check_passage(
    passage: Any,
    conversation: Conversation,
    redacted: RedactedConversation | None = None,
) -> list[str]:
    """Problems with one cited passage; [] when it is the exact text at its span."""
    redacted = redacted or redact_conversation(conversation)
    if not isinstance(passage, Mapping):
        return ["a passage is not an object"]
    turn_id = passage.get("turn_id")
    if (
        passage.get("conversation_id") != conversation.conversation_id
        or not isinstance(turn_id, str)
        or turn_id not in redacted.texts
    ):
        return [f"{turn_id}: cites a turn that is not in the conversation"]
    text = redacted.texts[turn_id]
    span = passage.get("span")
    if (
        not isinstance(span, list)
        or len(span) != 2
        or not all(type(v) is int for v in span)
        or not 0 <= span[0] < span[1] <= len(text)
    ):
        return [f"{turn_id}: span is not a range inside the turn"]
    problems = []
    if text[span[0] : span[1]] != passage.get("quote"):
        problems.append(f"{turn_id}: quote is not the exact text at its span")
    if passage.get("speaker") != conversation.turn(turn_id).speaker:
        problems.append(f"{turn_id}: speaker does not match")
    if passage.get("source_key") != conversation.source_key:
        problems.append(f"{turn_id}: source key does not match")
    if passage.get("source_version") != conversation.source["version"]:
        problems.append(f"{turn_id}: source version does not match")
    return problems
