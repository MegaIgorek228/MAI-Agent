"""Document review audit: when a staff decision was made and by whom.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-22
"""
import sqlalchemy as sa

from alembic import op

revision = "0012_document_review_audit"
down_revision = "0011_individual_achievements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing_columns = set()
    if op.get_bind().dialect.name == "sqlite" and not op.get_context().as_sql:
        # The original revision could leave both columns in SQLite before
        # failing to add the constraint and record the upgrade.
        existing_columns = {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns("application_documents")
        }

    with op.batch_alter_table("application_documents") as documents:
        if "reviewed_at" not in existing_columns:
            documents.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True)))
        if "reviewed_by" not in existing_columns:
            documents.add_column(sa.Column("reviewed_by", sa.Integer()))
        documents.create_foreign_key(
            "application_documents_reviewed_by_fkey",
            "users",
            ["reviewed_by"],
            ["id"],
            ondelete="SET NULL",
        )
        documents.create_index("ix_application_documents_reviewed_by", ["reviewed_by"])


def downgrade() -> None:
    with op.batch_alter_table("application_documents") as documents:
        documents.drop_constraint("application_documents_reviewed_by_fkey", type_="foreignkey")
        documents.drop_index("ix_application_documents_reviewed_by")
        documents.drop_column("reviewed_by")
        documents.drop_column("reviewed_at")
