"""add admission requirements and agent analysis fields

Revision ID: 0003_agent_integrations
Revises: 0002_applicant_knowledge_chat
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "0003_agent_integrations"
down_revision: str | Sequence[str] | None = "0002_applicant_knowledge_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("analysis_json", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("analysis_error", sa.Text(), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "knowledge_chunks",
            "embedding",
            type_=Vector(1024),
            existing_type=Vector(1536),
            postgresql_using="embedding::vector(1024)",
        )
    op.create_table(
        "admission_requirements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=100), nullable=False),
        sa.Column("target_program", sa.String(length=255), nullable=True),
        sa.Column("admission_basis", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admission_requirements_document_type",
        "admission_requirements",
        ["document_type"],
    )
    op.create_index(
        "ix_admission_requirements_target_program",
        "admission_requirements",
        ["target_program"],
    )
    op.create_index(
        "ix_admission_requirements_admission_basis",
        "admission_requirements",
        ["admission_basis"],
    )


def downgrade() -> None:
    op.drop_index("ix_admission_requirements_admission_basis", table_name="admission_requirements")
    op.drop_index("ix_admission_requirements_target_program", table_name="admission_requirements")
    op.drop_index("ix_admission_requirements_document_type", table_name="admission_requirements")
    op.drop_table("admission_requirements")
    op.drop_column("documents", "analysis_error")
    op.drop_column("documents", "analysis_json")
