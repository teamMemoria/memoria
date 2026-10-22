"""Post-call knowledge pipeline: ABCD conversations in, unapproved knowledge drafts out.

Stages (each usable on its own with local JSON, no backend or database):

* :func:`extract_drafts` -- issue #16, drafts with exact source passages.
* :func:`group_drafts` -- issue #17, groups, duplicates and existing-entry matches.
* :func:`find_conflicts` -- issue #18, possible conflicts with both passages.

The pipeline never approves anything. Every output is a draft or a finding
for an authorized human to act on through the backend.
"""

from .abcd import Conversation, read_conversation, read_conversations
from .conflicts import ConflictConfig, find_conflicts
from .errors import PipelineError
from .extraction import (
    ExtractionConfig,
    ExtractionResult,
    ModelExtractor,
    RuleExtractor,
    check_draft_citations,
    extract_drafts,
)
from .grouping import GroupingConfig, group_drafts
from .llm import FakeModelClient, ModelClient, OpenAICompatibleClient

__all__ = [
    "ConflictConfig",
    "Conversation",
    "ExtractionConfig",
    "ExtractionResult",
    "FakeModelClient",
    "GroupingConfig",
    "ModelClient",
    "ModelExtractor",
    "OpenAICompatibleClient",
    "PipelineError",
    "RuleExtractor",
    "check_draft_citations",
    "extract_drafts",
    "find_conflicts",
    "group_drafts",
    "read_conversation",
    "read_conversations",
]
