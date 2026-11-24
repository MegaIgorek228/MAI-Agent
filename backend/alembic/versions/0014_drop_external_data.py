"""Drop external data tables from the Backend service database.

Data architecture split: the synthetic ФИС ГИА registry now lives in its own
database (mai_fis_gia, seeded by app.init_databases), and the knowledge
corpus moves to the agent's own database (mai_agent). The service database
keeps only operational tables (agent_sessions, telegram_checkpoints).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0014_drop_external_data"
down_revision: str = "0013_sessionless_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("synthetic_ege_results")
    op.drop_table("synthetic_ege_candidates")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_sources")


def downgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url"),
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_chunks_source_id", "knowledge_chunks", ["source_id"])
    op.create_table(
        "synthetic_ege_candidates",
        sa.Column("candidate_id", sa.String(length=48), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("candidate_id"),
    )
    op.create_index(
        "ix_synthetic_ege_candidates_name_dob",
        "synthetic_ege_candidates",
        ["full_name", "date_of_birth"],
    )
    op.create_table(
        "synthetic_ege_results",
        sa.Column("candidate_id", sa.String(length=48), nullable=False),
        sa.Column("subject", sa.String(length=100), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("candidate_id", "subject", "year"),
        sa.CheckConstraint("score BETWEEN 0 AND 100"),
    )
