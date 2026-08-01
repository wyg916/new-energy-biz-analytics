"""Add governed memory, procedure, skill and SQLBot binding records."""

from alembic import op

from app.memory.models import P2B_MEMORY_TABLES

revision = "p2b_0001"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in P2B_MEMORY_TABLES:
        table.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(P2B_MEMORY_TABLES):
        table.drop(bind, checkfirst=True)
