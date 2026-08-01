"""Add preproduction acceptance, alert delivery and datasource governance state."""

from alembic import op
import sqlalchemy as sa

from app.preproduction.models import P4_PREPRODUCTION_TABLES


revision = "p4_0001"
down_revision = "p3_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in P4_PREPRODUCTION_TABLES:
        table.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(P4_PREPRODUCTION_TABLES):
        table.drop(bind, checkfirst=True)
