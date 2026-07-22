"""Structured session state and auditable analysis runs."""
from alembic import op

from app.models.business import AnalysisRun, SessionState

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    AnalysisRun.__table__.create(bind)
    SessionState.__table__.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    SessionState.__table__.drop(bind, checkfirst=True)
    AnalysisRun.__table__.drop(bind, checkfirst=True)
