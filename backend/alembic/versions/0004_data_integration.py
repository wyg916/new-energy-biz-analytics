"""Data source registry, dataset mappings and auditable staging preview."""

from alembic import op

from app.models.integration import (
    DataIngestionRun, DataSetDefinition, DataSourceConnection, IngestedStationPreview,
)

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = [
    DataSourceConnection.__table__,
    DataSetDefinition.__table__,
    DataIngestionRun.__table__,
    IngestedStationPreview.__table__,
]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
