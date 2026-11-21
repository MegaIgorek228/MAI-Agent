"""Keep the Telegram polling checkpoint across restarts."""

import sqlalchemy as sa
from alembic import op

revision = "0008_telegram_checkpoint"
down_revision = "0007_knowledge_embedding_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_checkpoints",
        sa.Column("bot_id", sa.String(64), primary_key=True),
        sa.Column("next_offset", sa.BigInteger(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("telegram_checkpoints")
