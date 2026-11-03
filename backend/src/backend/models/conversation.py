from datetime import date
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.models.columns import str_enum


class Speaker(StrEnum):
    AGENT = "agent"
    CUSTOMER = "customer"
    SYSTEM_ACTION = "system_action"


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # ID from the source dataset, e.g. "hvb-speaker-17".
    external_id: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="agent")


class Topic(Base):
    __tablename__ = "topics"
    # Topics belong to one dataset (company) so knowledge never mixes across them.
    __table_args__ = (UniqueConstraint("source_dataset", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_dataset: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="topic")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("source_dataset", "original_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_dataset: Mapped[str] = mapped_column(String(50))
    original_id: Mapped[str] = mapped_column(String(100))
    channel: Mapped[str] = mapped_column(String(20))
    # Real date from the source, when the source has one.
    conversation_date: Mapped[date | None] = mapped_column(Date)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), index=True)
    # File ID in the curated docs repo, e.g. "HVB-0001". Null for live calls.
    curated_id: Mapped[str | None] = mapped_column(String(20), unique=True)
    # Dataset-specific fields, kept exactly as the source provides them.
    source_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    customer_record: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    agent: Mapped[Agent] = relationship(back_populates="conversations")
    topic: Mapped[Topic | None] = relationship(back_populates="conversations")
    turns: Mapped[list["Turn"]] = relationship(
        back_populates="conversation",
        order_by="Turn.line_number",
        cascade="all, delete-orphan",
    )
    metrics: Mapped["ConversationMetric | None"] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        single_parent=True,
    )


class ConversationMetric(Base):
    __tablename__ = "conversation_metrics"
    __table_args__ = (
        CheckConstraint("turn_count >= 0"),
        CheckConstraint("agent_word_count >= 0"),
        CheckConstraint("customer_word_count >= 0"),
        CheckConstraint("agent_text_share BETWEEN 0 AND 1"),
        CheckConstraint("customer_text_share BETWEEN 0 AND 1"),
        CheckConstraint("call_elapsed_ms >= 0"),
        CheckConstraint("agent_speaking_ms >= 0"),
        CheckConstraint("customer_speaking_ms >= 0"),
        CheckConstraint("average_turn_duration_ms >= 0"),
        CheckConstraint("asr_word_error_rate >= 0"),
        CheckConstraint("asr_compared_turn_count >= 0"),
        CheckConstraint("system_action_count >= 0"),
        CheckConstraint("documented_action_count >= 0"),
    )

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    turn_count: Mapped[int] = mapped_column(Integer)
    agent_word_count: Mapped[int] = mapped_column(Integer)
    customer_word_count: Mapped[int] = mapped_column(Integer)
    agent_text_share: Mapped[float | None] = mapped_column(Float)
    customer_text_share: Mapped[float | None] = mapped_column(Float)
    call_elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    agent_speaking_ms: Mapped[int | None] = mapped_column(Integer)
    customer_speaking_ms: Mapped[int | None] = mapped_column(Integer)
    average_turn_duration_ms: Mapped[float | None] = mapped_column(Float)
    asr_word_error_rate: Mapped[float | None] = mapped_column(Float)
    asr_compared_turn_count: Mapped[int | None] = mapped_column(Integer)
    system_action_count: Mapped[int | None] = mapped_column(Integer)
    documented_action_count: Mapped[int | None] = mapped_column(Integer)

    conversation: Mapped[Conversation] = relationship(back_populates="metrics")


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (UniqueConstraint("conversation_id", "line_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    # The source's turn number. Kept as-is (it can have gaps) so evidence
    # references match the original transcript.
    line_number: Mapped[int]
    speaker: Mapped[Speaker] = mapped_column(str_enum(Speaker, "speaker"))
    text: Mapped[str] = mapped_column(Text)

    conversation: Mapped[Conversation] = relationship(back_populates="turns")
