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
    with op.batch_alter_table("chat_messages") as messages:
        messages.add_column(sa.Column("image_document_id", sa.Integer(), nullable=True))
        messages.create_index("ix_chat_messages_image_document_id", ["image_document_id"])
        messages.create_foreign_key(
            "fk_chat_messages_image_document_id",
            "documents",
            ["image_document_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as messages:
        messages.drop_constraint("fk_chat_messages_image_document_id", type_="foreignkey")
        messages.drop_index("ix_chat_messages_image_document_id")
        messages.drop_column("image_document_id")
