"""Connect Layer 2 draft generation to the knowledge import service."""

import json
from functools import partial
from pathlib import Path

from backend.entities.inferred_knowledge import Settings
from backend.entities.policies import SOURCE_PREFIX
from backend.frameworks.data_access.knowledge_import import KnowledgeImportService
from backend.interface_adapters.drafts import draft_candidates


def pilot_knowledge_import(sessions, settings):
    limits = Settings(
        min_calls=settings.knowledge_draft_threshold,
        conflict_calls=settings.knowledge_conflict_threshold,
    )
    questions = (
        json.loads(Path(settings.layer2_policy_questions).read_text())
        if settings.layer2_policy_questions
        else ()
    )
    return KnowledgeImportService(
        sessions,
        generate=partial(draft_candidates, settings=limits, questions=questions),
        source_prefix=SOURCE_PREFIX,
    )
