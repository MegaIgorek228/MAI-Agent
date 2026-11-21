"""link chat messages to attached image documents

Revision ID: 0005_chat_message_image
Revises: 0004_telegram_identity
Create Date: 2026-11-21
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_chat_message_image"
down_revision: str | Sequence[str] | None = "0004_telegram_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("image_document_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_chat_messages_image_document_id", "chat_messages", ["image_document_id"])
    op.create_foreign_key(
        "fk_chat_messages_image_document_id",
        "chat_messages",
        "documents",
        ["image_document_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_chat_messages_image_document_id", "chat_messages", type_="foreignkey")
    op.drop_index("ix_chat_messages_image_document_id", table_name="chat_messages")
    op.drop_column("chat_messages", "image_document_id")
