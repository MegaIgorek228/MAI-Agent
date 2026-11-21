"""record the embedding model used for knowledge chunks

Revision ID: 0007_knowledge_embedding_model
Revises: 0006_admissions_workflow
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_knowledge_embedding_model"
down_revision = "0006_admissions_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_chunks", sa.Column("embedding_model", sa.String(length=255)))


def downgrade() -> None:
    op.drop_column("knowledge_chunks", "embedding_model")
