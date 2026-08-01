"""Merge frontend data lineage and P2B memory heads.

Revision ID: p3_merge_0001
Revises: 0015, p2b_0001
"""

revision = "p3_merge_0001"
down_revision = ("0015", "p2b_0001")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join the two already-applied schema branches without changing data."""


def downgrade() -> None:
    """Alembic restores both predecessor heads when the merge is downgraded."""
