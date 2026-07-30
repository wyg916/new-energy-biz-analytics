"""Bind every ChatBI conversation to one identity scope and scenario."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_scenario_session_binding",
        sa.Column("conversation_id", sa.String(length=48), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=96), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(
        "ix_chat_scenario_session_scope",
        "chat_scenario_session_binding",
        ["tenant_id", "workspace_id", "subject_id", "scenario_id"],
    )


def downgrade() -> None:
    op.drop_table("chat_scenario_session_binding")
