"""Add continuously runnable and auditable memory lifecycle jobs.

Revision ID: memory_41_0001
Revises: data_0001
"""

import sqlalchemy as sa
from alembic import op

from app.memory.models import MEMORY_LIFECYCLE_TABLES


revision = "memory_41_0001"
down_revision = "data_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("memory_record")}
    with op.batch_alter_table("memory_record") as batch:
        if "recall_count" not in existing_columns:
            batch.add_column(sa.Column("recall_count", sa.Integer(), nullable=False, server_default="0"))
        if "last_recalled_at" not in existing_columns:
            batch.add_column(sa.Column("last_recalled_at", sa.DateTime(timezone=True), nullable=True))
        if "lifecycle_transition_at" not in existing_columns:
            batch.add_column(sa.Column("lifecycle_transition_at", sa.DateTime(timezone=True), nullable=True))
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("memory_record")}
    if "ix_memory_record_last_recalled_at" not in existing_indexes:
        with op.batch_alter_table("memory_record") as batch:
            batch.create_index("ix_memory_record_last_recalled_at", ["last_recalled_at"])
    for table in MEMORY_LIFECYCLE_TABLES:
        table.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(MEMORY_LIFECYCLE_TABLES):
        table.drop(bind, checkfirst=True)
    with op.batch_alter_table("memory_record") as batch:
        batch.drop_index("ix_memory_record_last_recalled_at")
        batch.drop_column("lifecycle_transition_at")
        batch.drop_column("last_recalled_at")
        batch.drop_column("recall_count")
