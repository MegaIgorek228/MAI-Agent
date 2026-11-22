"""Add individual achievements with an append-only review history."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_individual_achievements"
down_revision: str | Sequence[str] | None = "0010_staff_invites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "individual_achievements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("applicant_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id", ondelete="SET NULL")),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("level", sa.String(32)),
        sa.Column("achieved_on", sa.Date(), nullable=False),
        sa.Column("organization", sa.String(255)),
        sa.Column("description", sa.Text()),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("review_comment", sa.Text()),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_individual_achievements_applicant_id", "individual_achievements", ["applicant_id"])
    op.create_index("ix_individual_achievements_application_id", "individual_achievements", ["application_id"])
    op.create_index("ix_individual_achievements_category", "individual_achievements", ["category"])
    op.create_index("ix_individual_achievements_document_id", "individual_achievements", ["document_id"])
    op.create_index("ix_individual_achievements_status", "individual_achievements", ["status"])
    op.create_table(
        "achievement_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "achievement_id",
            sa.Integer(),
            sa.ForeignKey("individual_achievements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_achievement_reviews_achievement_id", "achievement_reviews", ["achievement_id"])


def downgrade() -> None:
    op.drop_index("ix_achievement_reviews_achievement_id", table_name="achievement_reviews")
    op.drop_table("achievement_reviews")
    for index in (
        "ix_individual_achievements_status",
        "ix_individual_achievements_document_id",
        "ix_individual_achievements_category",
        "ix_individual_achievements_application_id",
        "ix_individual_achievements_applicant_id",
    ):
        op.drop_index(index, table_name="individual_achievements")
    op.drop_table("individual_achievements")
