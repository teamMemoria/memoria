from sqlalchemy import Select, select

from backend.models import Conversation, KnowledgeDraft, KnowledgeEntry


def conversations_for(organization_id: int) -> Select[tuple[Conversation]]:
    return select(Conversation).where(Conversation.organization_id == organization_id)


def knowledge_drafts_for(organization_id: int) -> Select[tuple[KnowledgeDraft]]:
    return select(KnowledgeDraft).where(
        KnowledgeDraft.organization_id == organization_id
    )


def knowledge_entries_for(organization_id: int) -> Select[tuple[KnowledgeEntry]]:
    return select(KnowledgeEntry).where(
        KnowledgeEntry.organization_id == organization_id
    )
