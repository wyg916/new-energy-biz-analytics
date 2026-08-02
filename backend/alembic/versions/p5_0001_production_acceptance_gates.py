"""Add auditable P5 production acceptance gates.

Revision ID: p5_0001
Revises: p4_0001
"""

from alembic import op

from app.production_acceptance.models import P5_PRODUCTION_ACCEPTANCE_TABLES


revision = "p5_0001"
down_revision = "p4_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in P5_PRODUCTION_ACCEPTANCE_TABLES:
        table.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(P5_PRODUCTION_ACCEPTANCE_TABLES):
        table.drop(bind, checkfirst=True)
