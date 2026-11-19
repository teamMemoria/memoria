from backend.core.database import Base as _Base
from backend.frameworks.database.models.analysis import (
    ACTIVE_RUN_STATUSES,
    AnalysisRun,
    AnalysisRunStatus,
)
from backend.frameworks.database.models.audit import (
    AgentContext,
    Audit,
    FeedbackFlag,
    Finding,
    FindingCategory,
    FindingResult,
    ManagerReview,
    ManagerReviewOutcome,
    finding_evidence,
)
from backend.frameworks.database.models.conversation import (
    Agent,
    Conversation,
    ConversationMetric,
    Speaker,
    Topic,
    Turn,
)
from backend.frameworks.database.models.evaluation import (
    EvaluationCriterion,
    EvaluationForm,
    EvaluationFormVersion,
)
from backend.frameworks.database.models.indexes import (
    add_query_indexes as _add_query_indexes,
)
from backend.frameworks.database.models.knowledge import (
    EMBEDDING_DIM,
    DraftStatus,
    EntryStatus,
    KnowledgeConflict,
    KnowledgeDraft,
    KnowledgeDraftEntryMatch,
    KnowledgeDraftPassage,
    KnowledgeEntry,
    KnowledgeReview,
    ReviewAction,
    knowledge_draft_conversations,
)
from backend.frameworks.database.models.organization import (
    Organization,
    OrganizationMembership,
    User,
    UserRole,
)

__all__ = [
    "ACTIVE_RUN_STATUSES",
    "EMBEDDING_DIM",
    "Agent",
    "AgentContext",
    "AnalysisRun",
    "AnalysisRunStatus",
    "Audit",
    "Conversation",
    "ConversationMetric",
    "DraftStatus",
    "EntryStatus",
    "EvaluationCriterion",
    "EvaluationForm",
    "EvaluationFormVersion",
    "FeedbackFlag",
    "Finding",
    "FindingCategory",
    "FindingResult",
    "KnowledgeConflict",
    "KnowledgeDraft",
    "KnowledgeDraftEntryMatch",
    "KnowledgeDraftPassage",
    "KnowledgeEntry",
    "KnowledgeReview",
    "ManagerReview",
    "ManagerReviewOutcome",
    "Organization",
    "OrganizationMembership",
    "ReviewAction",
    "Speaker",
    "Topic",
    "Turn",
    "User",
    "UserRole",
    "finding_evidence",
    "knowledge_draft_conversations",
]


_add_query_indexes(_Base.metadata)
