"""Add one-time staff registration invitations (hashed codes)."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_staff_invites"
down_revision: str | Sequence[str] | None = "0009_synthetic_ege_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staff_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("note", sa.String(255)),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("used_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_staff_invites_code_hash", "staff_invites", ["code_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_staff_invites_code_hash", table_name="staff_invites")
    op.drop_table("staff_invites")
