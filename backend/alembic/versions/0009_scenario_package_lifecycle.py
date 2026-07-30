"""Add tenant-scoped scenario package lifecycle metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scenario_package_release",
        sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="tenant-alpha"),
    )
    op.add_column(
        "scenario_package_release",
        sa.Column("workspace_id", sa.String(length=64), nullable=False, server_default="workspace-alpha"),
    )
    op.add_column(
        "scenario_package_release",
        sa.Column("package_root", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "scenario_package_release",
        sa.Column("platform_api_range", sa.String(length=64), nullable=False, server_default="*"),
    )
    op.add_column(
        "scenario_package_release",
        sa.Column("validation_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "scenario_package_release",
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scenario_package_release",
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "scenario_package_release",
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_scenario_package_release_tenant_id",
        "scenario_package_release",
        ["tenant_id"],
    )
    op.create_index(
        "ix_scenario_package_release_workspace_id",
        "scenario_package_release",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scenario_package_release_workspace_id",
        table_name="scenario_package_release",
    )
    op.drop_index(
        "ix_scenario_package_release_tenant_id",
        table_name="scenario_package_release",
    )
    for column in (
        "disabled_at",
        "activated_at",
        "validated_at",
        "validation_json",
        "platform_api_range",
        "package_root",
        "workspace_id",
        "tenant_id",
    ):
        op.drop_column("scenario_package_release", column)

