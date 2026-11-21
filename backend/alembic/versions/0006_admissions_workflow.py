"""Add versioned admission rules, applications and synthetic exam verification."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_admissions_workflow"
down_revision: str | Sequence[str] | None = "0005_chat_message_image"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admission_rule_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_year", sa.Integer(), nullable=False),
        sa.Column("program", sa.String(255), nullable=False),
        sa.Column("admission_basis", sa.String(100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("document_requirements", sa.JSON(), nullable=False),
        sa.Column("subject_minima", sa.JSON(), nullable=False),
        sa.UniqueConstraint("campaign_year", "program", "admission_basis", "revision"),
    )
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("applicant_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_year", sa.Integer(), nullable=False),
        sa.Column("program", sa.String(255), nullable=False),
        sa.Column("admission_basis", sa.String(100), nullable=False),
        sa.Column("rules_id", sa.Integer(), sa.ForeignKey("admission_rule_sets.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("synthetic_candidate_id", sa.String(48), nullable=True),
        sa.Column("scores_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_applications_applicant_id", "applications", ["applicant_id"])
    op.create_index("ix_applications_status", "applications", ["status"])
    op.create_table(
        "application_documents",
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("review_status", sa.String(20), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
    )
    op.create_index("ix_application_documents_document_id", "application_documents", ["document_id"])
    op.create_table(
        "application_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_application_events_application_id", "application_events", ["application_id"])
    op.create_table(
        "ege_scores",
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("subject", sa.String(100), primary_key=True),
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.CheckConstraint("score BETWEEN 0 AND 100"),
    )
    op.create_table(
        "synthetic_ege_results",
        sa.Column("candidate_id", sa.String(48), primary_key=True),
        sa.Column("subject", sa.String(100), primary_key=True),
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.CheckConstraint("score BETWEEN 0 AND 100"),
    )
    op.create_table(
        "ege_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scores_revision", sa.Integer(), nullable=False),
        sa.Column("reference_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("missing_subjects", sa.JSON(), nullable=False),
        sa.Column("mismatched_subjects", sa.JSON(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("application_id", "scores_revision", "reference_digest"),
    )


def downgrade() -> None:
    op.drop_table("ege_verifications")
    op.drop_table("synthetic_ege_results")
    op.drop_table("ege_scores")
    op.drop_table("application_events")
    op.drop_table("application_documents")
    op.drop_table("applications")
    op.drop_table("admission_rule_sets")
