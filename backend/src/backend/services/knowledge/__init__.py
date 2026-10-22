"""Post-call knowledge pipeline: ABCD conversations in, unapproved knowledge drafts out.

Stages (each usable on its own with local JSON, no backend or database):

* :func:`extract_drafts` -- issue #16, drafts with exact source passages.

The pipeline never approves anything. Every output is a draft or a finding
for an authorized human to act on through the backend.
"""

from .abcd import Conversation, read_conversation, read_conversations
from .errors import PipelineError
from .extraction import (
    ExtractionConfig,
    ExtractionResult,
    ModelExtractor,
    RuleExtractor,
    check_draft_citations,
    extract_drafts,
)
from .llm import FakeModelClient, ModelClient, OpenAICompatibleClient

__all__ = [
    "Conversation",
    "ExtractionConfig",
    "ExtractionResult",
    "FakeModelClient",
    "ModelClient",
    "ModelExtractor",
    "OpenAICompatibleClient",
    "PipelineError",
    "RuleExtractor",
    "check_draft_citations",
    "extract_drafts",
    "read_conversation",
    "read_conversations",
]
