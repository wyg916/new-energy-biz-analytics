"""Add DATA-4.1 open-source lineage and raw/staging schemas.

Revision ID: data_0001
Revises: p5_0001
"""

from alembic import op

from app.models.open_data import OPEN_DATA_TABLES


revision = "data_0001"
down_revision = "p5_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in OPEN_DATA_TABLES:
        table.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(OPEN_DATA_TABLES):
        table.drop(bind, checkfirst=True)
