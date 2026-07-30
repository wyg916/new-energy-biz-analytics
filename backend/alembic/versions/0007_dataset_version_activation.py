"""Generic immutable dataset release, activation, and rollback records."""

from alembic import op

from app.models.platform_data import DATASET_TABLES

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in DATASET_TABLES:
        table.create(bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(DATASET_TABLES):
        table.drop(bind, checkfirst=True)

