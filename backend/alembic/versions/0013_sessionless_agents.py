"""Sessionless architecture: AgentSession is the only unit of user context.

The user/role/invite/profile system (users, staff_invites, applicant_profiles,
documents, applications with its child tables, chat_sessions/chat_messages,
telegram_identities) is replaced by a minimal ``agent_sessions`` table mapping
chat surfaces (web, telegram) to Hermes sessions. The conversation transcript
and the agent's long-term memory live in Hermes' own session store
(``~/.hermes/state.db``) — the backend no longer duplicates it and reads
history back through the ACP ``session/load`` replay.

Revision ID: 0013_sessionless_agents
Revises: 0012_document_review_audit
Create Date: 2026-11-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_sessionless_agents"
down_revision = "0012_document_review_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=True, unique=True),
        sa.Column("hermes_session_id", sa.String(255), nullable=True, unique=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("source IN ('web', 'telegram')", name="ck_agent_sessions_source"),
    )
    # Children before parents (FK dependencies in the legacy schema).
    for table in (
        "achievement_reviews",
        "chat_messages",
        "chat_sessions",
        "telegram_identities",
        "application_documents",
        "application_events",
        "ege_scores",
        "ege_verifications",
        "individual_achievements",
        "documents",
        "applications",
        "admission_requirements",
        "admission_rule_sets",
        "applicant_profiles",
        "staff_invites",
        "users",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")


def downgrade() -> None:
    raise NotImplementedError(
        "The sessionless migration is one-way: the legacy user tables and their "
        "data are removed by design. Restore the pre-migration backup "
        "(mai_agent_pre_sessionless_*.sql) instead of downgrading."
    )
