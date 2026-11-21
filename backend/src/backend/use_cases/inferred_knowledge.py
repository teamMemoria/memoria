"""Build a company's inferred knowledge base, let managers change it, score calls.

Where claims come from and where the knowledge base is kept are details. The
interactors only see the two small interfaces below, so the text processing
or the storage can change without touching the rules.
"""

from collections.abc import Iterable, Sequence
from typing import Protocol

from backend.entities.inferred_knowledge import (
    CallScore,
    FactClaim,
    InferenceSettings,
    InvalidKnowledgeInput,
    KnowledgeBase,
    Override,
    apply_overrides,
    build_knowledge_base,
    check_override,
    score_call,
)


class ClaimSource(Protocol):
    def claims(self, company_id: str) -> Iterable[FactClaim]: ...


class KnowledgeBaseStore(Protocol):
    def load(self, company_id: str) -> KnowledgeBase | None: ...
    def save(self, knowledge_base: KnowledgeBase) -> None: ...
    def overrides(self, company_id: str) -> Sequence[Override]: ...
    def add_override(self, company_id: str, override: Override) -> None: ...


class KnowledgeBaseNotBuilt(LookupError):
    pass


class NoCallsToLearnFrom(InvalidKnowledgeInput):
    pass


def _require(store: KnowledgeBaseStore, company_id: str) -> KnowledgeBase:
    knowledge_base = store.load(company_id)
    if knowledge_base is None:
        raise KnowledgeBaseNotBuilt(
            f"No knowledge base has been built for {company_id} yet."
        )
    return knowledge_base


class InferKnowledgeBase:
    """Relearn a company's rules from every audited call so far.

    The whole knowledge base is rebuilt each time, from all claims, so counts
    never drift and running it twice gives the same result. Topics keep their
    ids from the previous version, and managers' changes are applied on top,
    so they survive every rebuild. If no call gave a value, nothing is saved:
    an empty run must never replace a real knowledge base.
    """

    def __init__(
        self,
        source: ClaimSource,
        store: KnowledgeBaseStore,
        settings: InferenceSettings | None = None,
    ):
        self.source = source
        self.store = store
        self.settings = settings or InferenceSettings()

    def execute(self, company_id: str) -> KnowledgeBase:
        claims = list(self.source.claims(company_id))
        if not claims:
            raise NoCallsToLearnFrom("None of the calls gave a value to learn from.")
        learned = build_knowledge_base(
            company_id, claims, self.settings, self.store.load(company_id)
        )
        knowledge_base = apply_overrides(learned, self.store.overrides(company_id))
        self.store.save(knowledge_base)
        return knowledge_base


class RecordOverride:
    """Record a manager's change. It shows up from the next rebuild on."""

    def __init__(self, store: KnowledgeBaseStore):
        self.store = store

    def execute(self, company_id: str, override: Override) -> None:
        check_override(_require(self.store, company_id), override)
        self.store.add_override(company_id, override)


class ScoreCall:
    """Check the information given in one call against the company's rules."""

    def __init__(self, store: KnowledgeBaseStore):
        self.store = store

    def execute(
        self, company_id: str, call_id: str, claims: Sequence[FactClaim]
    ) -> CallScore:
        return score_call(company_id, call_id, claims, _require(self.store, company_id))
