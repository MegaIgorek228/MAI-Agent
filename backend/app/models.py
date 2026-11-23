"""Database models for the sessionless MAI-Agent architecture.

The only unit of user context is an :class:`AgentSession` — a Hermes agent
session bound to a chat surface (Web or Telegram). There are no user
accounts, roles or profiles: the conversation transcript and the agent's
long-term memory live in Hermes' own session store (``state.db``),
referenced by ``AgentSession.hermes_session_id``.
"""

from datetime import date, datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AgentSession(Base):
    """A Hermes agent session owned by a chat surface.

    ``source`` is ``web`` or ``telegram``. ``external_id`` holds the Telegram
    chat id for telegram sessions — the only mapping between a chat and its
    session; web sessions are referenced by the client via their UUID and
    have no external id. The transcript itself is not stored here: it
    belongs to the Hermes session (``hermes_session_id``) and is read back
    through the ACP ``session/load`` replay.
    """

    __tablename__ = "agent_sessions"
    __table_args__ = (
        CheckConstraint("source IN ('web', 'telegram')", name="ck_agent_sessions_source"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    hermes_session_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    embedding_model: Mapped[str | None] = mapped_column(String(255))


class SyntheticEgeResult(Base):
    __tablename__ = "synthetic_ege_results"
    __table_args__ = (CheckConstraint("score BETWEEN 0 AND 100"),)

    candidate_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    subject: Mapped[str] = mapped_column(String(100), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    score: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="valid")


class SyntheticEgeCandidate(Base):
    """A synthetic person in the test EGE registry: full name plus date of birth.

    The registry is reference data: it is only written by the administrative
    fixture loader (``app.synthetic_ege_registry``), never by chat routes or
    MCP tools. ``full_name`` is stored in its natural form; lookups normalize
    case and whitespace, so several rows may intentionally match one name and
    date of birth (ambiguous match, no unique constraint).
    """

    __tablename__ = "synthetic_ege_candidates"
    __table_args__ = (Index("ix_synthetic_ege_candidates_name_dob", "full_name", "date_of_birth"),)

    candidate_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
