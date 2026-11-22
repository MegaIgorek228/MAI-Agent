from datetime import date, datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserRole(StrEnum):
    applicant = "applicant"
    student = "student"
    admissions_staff = "admissions_staff"
    administrator = "administrator"


class StaffInvite(Base):
    """A one-time, expiring invitation for staff registration.

    Only a SHA-256 hash of the code is stored; the plaintext code is shown
    once at creation (administrative CLI) and never persisted.
    """

    __tablename__ = "staff_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    note: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default=UserRole.applicant.value)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ApplicantProfile(Base):
    __tablename__ = "applicant_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(32))
    target_program: Mapped[str | None] = mapped_column(String(255))
    admission_basis: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(150))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    document_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    extracted_text: Mapped[str | None] = mapped_column(Text)
    review_message: Mapped[str | None] = mapped_column(Text)
    analysis_json: Mapped[str | None] = mapped_column(Text)
    analysis_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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


class AdmissionRequirement(Base):
    __tablename__ = "admission_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_type: Mapped[str] = mapped_column(String(100), index=True)
    target_program: Mapped[str | None] = mapped_column(String(255), index=True)
    admission_basis: Mapped[str | None] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(255))
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))


class AdmissionRuleSet(Base):
    __tablename__ = "admission_rule_sets"
    __table_args__ = (UniqueConstraint("campaign_year", "program", "admission_basis", "revision"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_year: Mapped[int] = mapped_column(Integer)
    program: Mapped[str] = mapped_column(String(255))
    admission_basis: Mapped[str] = mapped_column(String(100))
    revision: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    document_requirements: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    subject_minima: Mapped[dict[str, int]] = mapped_column(JSON)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    campaign_year: Mapped[int] = mapped_column(Integer)
    program: Mapped[str] = mapped_column(String(255))
    admission_basis: Mapped[str] = mapped_column(String(100))
    rules_id: Mapped[int | None] = mapped_column(ForeignKey("admission_rule_sets.id"))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    review_note: Mapped[str | None] = mapped_column(Text)
    synthetic_candidate_id: Mapped[str | None] = mapped_column(String(48))
    scores_revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class ApplicationDocument(Base):
    __tablename__ = "application_documents"

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True,
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True, index=True,
    )
    review_status: Mapped[str | None] = mapped_column(String(20))
    review_note: Mapped[str | None] = mapped_column(Text)


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True,
    )
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EgeScore(Base):
    __tablename__ = "ege_scores"
    __table_args__ = (CheckConstraint("score BETWEEN 0 AND 100"),)

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True,
    )
    subject: Mapped[str] = mapped_column(String(100), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    score: Mapped[int] = mapped_column(Integer)


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
    fixture loader (``app.synthetic_ege_registry``), never by applicant-facing
    routes or MCP tools. ``full_name`` is stored in its natural form; lookups
    normalize case and whitespace, so several rows may intentionally match
    one name and date of birth (ambiguous match, no unique constraint).
    """

    __tablename__ = "synthetic_ege_candidates"
    __table_args__ = (Index("ix_synthetic_ege_candidates_name_dob", "full_name", "date_of_birth"),)

    candidate_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EgeVerification(Base):
    __tablename__ = "ege_verifications"
    __table_args__ = (UniqueConstraint("application_id", "scores_revision", "reference_digest"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    scores_revision: Mapped[int] = mapped_column(Integer)
    reference_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    missing_subjects: Mapped[list[str]] = mapped_column(JSON)
    mismatched_subjects: Mapped[list[str]] = mapped_column(JSON)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IndividualAchievement(Base):
    """An applicant-declared individual achievement (olympiad, sport, GTO, ...).

    Three distinct concepts are modelled deliberately: the declared achievement
    (this row), the staff review (``status`` + ``AchievementReview`` history),
    and admission scoring (out of scope — a confirmed achievement may later be
    counted by separate admission rules; no points are ever assigned here).
    """

    __tablename__ = "individual_achievements"

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255))
    level: Mapped[str | None] = mapped_column(String(32))
    achieved_on: Mapped[date] = mapped_column(Date)
    organization: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AchievementReview(Base):
    """Append-only history of lifecycle actions on an individual achievement."""

    __tablename__ = "achievement_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    achievement_id: Mapped[int] = mapped_column(
        ForeignKey("individual_achievements.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    hermes_session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    channel: Mapped[str] = mapped_column(String(32), default="web")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    image_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TelegramIdentity(Base):
    __tablename__ = "telegram_identities"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    pairing_code: Mapped[str | None] = mapped_column(String(12), unique=True, index=True)
    pairing_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
