"""Core business dimensions, facts, generation and metric catalog."""
from alembic import op

from app.models.business import (
    ChargingSession, City, DataGenerationRun, DateDimension, Device,
    DeviceStatusEvent, EnergyCost, MetricDefinition, OperationExpense,
    Region, SimulatedUser, Station,
)

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = [
    Region.__table__, City.__table__, Station.__table__, Device.__table__,
    SimulatedUser.__table__, DateDimension.__table__, ChargingSession.__table__,
    EnergyCost.__table__, OperationExpense.__table__, DeviceStatusEvent.__table__,
    DataGenerationRun.__table__, MetricDefinition.__table__,
]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
