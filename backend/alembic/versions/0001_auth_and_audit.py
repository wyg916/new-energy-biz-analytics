"""Authentication and audit baseline."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("app_user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("region_code", sa.String(32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_app_user_username", "app_user", ["username"], unique=True)
    op.create_index("ix_app_user_role", "app_user", ["role"])
    op.create_table("audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("app_user")
