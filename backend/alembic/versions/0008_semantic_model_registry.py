"""Generic versioned semantic model registry."""

from alembic import op

from app.models.semantic import SEMANTIC_TABLES

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in SEMANTIC_TABLES:
        table.create(bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(SEMANTIC_TABLES):
        table.drop(bind, checkfirst=True)

