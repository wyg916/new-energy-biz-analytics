"""Versioned charging_ops package and immutable published station snapshots."""

from alembic import op

from app.models.integration import PublishedStationSnapshot, ScenarioPackageRelease

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TABLES = [ScenarioPackageRelease.__table__, PublishedStationSnapshot.__table__]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
