"""add Telegram identity pairing

Revision ID: 0004_telegram_identity
Revises: 0003_agent_integrations
Create Date: 2026-11-18
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_telegram_identity"
down_revision: str | Sequence[str] | None = "0003_agent_integrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("pairing_code", sa.String(length=12), nullable=True),
        sa.Column("pairing_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id"),
        sa.UniqueConstraint("pairing_code"),
    )
    op.create_index("ix_telegram_identities_chat_id", "telegram_identities", ["chat_id"])
    op.create_index("ix_telegram_identities_pairing_code", "telegram_identities", ["pairing_code"])
    op.create_index("ix_telegram_identities_user_id", "telegram_identities", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_telegram_identities_user_id", table_name="telegram_identities")
    op.drop_index("ix_telegram_identities_pairing_code", table_name="telegram_identities")
    op.drop_index("ix_telegram_identities_chat_id", table_name="telegram_identities")
    op.drop_table("telegram_identities")
