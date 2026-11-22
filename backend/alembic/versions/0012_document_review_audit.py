"""Document review audit: when a staff decision was made and by whom.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_document_review_audit"
down_revision = "0011_individual_achievements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "application_documents",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "application_documents",
        sa.Column(
            "reviewed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_application_documents_reviewed_by", "application_documents", ["reviewed_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_application_documents_reviewed_by", table_name="application_documents")
    op.drop_column("application_documents", "reviewed_by")
    op.drop_column("application_documents", "reviewed_at")
