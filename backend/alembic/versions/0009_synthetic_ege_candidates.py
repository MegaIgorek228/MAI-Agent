"""Add the synthetic EGE candidate registry (full name + date of birth)."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_synthetic_ege_candidates"
down_revision: str | Sequence[str] | None = "0008_telegram_checkpoint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "synthetic_ege_candidates",
        sa.Column("candidate_id", sa.String(48), primary_key=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_synthetic_ege_candidates_name_dob",
        "synthetic_ege_candidates",
        ["full_name", "date_of_birth"],
    )


def downgrade() -> None:
    op.drop_index("ix_synthetic_ege_candidates_name_dob", table_name="synthetic_ege_candidates")
    op.drop_table("synthetic_ege_candidates")
