"""Auditable ingestion quality, approval and dataset release workflow."""

from alembic import op

from app.models.integration import DataIngestionQualityCheck, DataIngestionReview

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TABLES = [
    DataIngestionQualityCheck.__table__,
    DataIngestionReview.__table__,
]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
