"""Add enterprise identity, authorization, credential and governance records."""

from alembic import op

from app.governance.models import P3_GOVERNANCE_TABLES

revision = "p3_0001"
down_revision = "p3_merge_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in P3_GOVERNANCE_TABLES:
        table.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(P3_GOVERNANCE_TABLES):
        table.drop(bind, checkfirst=True)
