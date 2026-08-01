"""Persist metric presentation metadata used by the frontend."""

import json

import sqlalchemy as sa
from alembic import op

from app.services.metric_catalog import METRIC_DETAILS, SUPPORTED_GRAINS

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


COLUMNS = (
    sa.Column(
        "business_domain",
        sa.String(length=64),
        nullable=False,
        server_default="经营分析",
    ),
    sa.Column(
        "definition",
        sa.Text(),
        nullable=False,
        server_default="",
    ),
    sa.Column(
        "source_tables_json",
        sa.Text(),
        nullable=False,
        server_default="[]",
    ),
    sa.Column(
        "supported_grains_json",
        sa.Text(),
        nullable=False,
        server_default='["day", "week", "month"]',
    ),
    sa.Column(
        "metric_type",
        sa.String(length=32),
        nullable=False,
        server_default="aggregation",
    ),
)


def _column_names() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("metric_definition")
    }


def upgrade() -> None:
    existing = _column_names()
    for column in COLUMNS:
        if column.name not in existing:
            op.add_column("metric_definition", column)

    metric_definition = sa.table(
        "metric_definition",
        sa.column("metric_id", sa.String()),
        sa.column("business_domain", sa.String()),
        sa.column("definition", sa.Text()),
        sa.column("source_tables_json", sa.Text()),
        sa.column("supported_grains_json", sa.Text()),
        sa.column("metric_type", sa.String()),
    )
    bind = op.get_bind()
    for metric_id, detail in METRIC_DETAILS.items():
        bind.execute(
            metric_definition.update()
            .where(metric_definition.c.metric_id == metric_id)
            .values(
                business_domain=detail["business_domain"],
                definition=detail["definition"],
                source_tables_json=json.dumps(
                    detail["source_tables"],
                    ensure_ascii=False,
                ),
                supported_grains_json=json.dumps(
                    SUPPORTED_GRAINS,
                    ensure_ascii=False,
                ),
                metric_type=detail["metric_type"],
            )
        )


def downgrade() -> None:
    existing = _column_names()
    for column in reversed(COLUMNS):
        if column.name in existing:
            with op.batch_alter_table("metric_definition") as batch:
                batch.drop_column(column.name)
