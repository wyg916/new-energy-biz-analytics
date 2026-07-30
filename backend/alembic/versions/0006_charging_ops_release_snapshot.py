"""Versioned charging_ops package and immutable published station snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "scenario_package_release",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("manifest_checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("source_batch_id", sa.String(length=64), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "scenario_id", "version", name="uq_scenario_package_version"
        ),
    )
    op.create_index(
        "ix_scenario_package_release_scenario_id",
        "scenario_package_release",
        ["scenario_id"],
    )
    op.create_index(
        "ix_scenario_package_release_status",
        "scenario_package_release",
        ["status"],
    )
    op.create_index(
        "ix_scenario_package_release_source_batch_id",
        "scenario_package_release",
        ["source_batch_id"],
    )
    op.create_table(
        "published_station_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "review_id",
            sa.String(length=64),
            sa.ForeignKey("data_ingestion_review.review_id"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            sa.String(length=64),
            sa.ForeignKey("data_set_definition.dataset_id"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("data_ingestion_run.run_id"),
            nullable=False,
        ),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_version", sa.String(length=32), nullable=False),
        sa.Column("release_version", sa.String(length=48), nullable=False),
        sa.Column("source_record_id", sa.String(length=128), nullable=False),
        sa.Column("station_id", sa.String(length=32), nullable=False),
        sa.Column("station_name", sa.String(length=128), nullable=False),
        sa.Column("region_id", sa.String(length=32), nullable=False),
        sa.Column("city_id", sa.String(length=32), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end_exclusive", sa.Date(), nullable=False),
        sa.Column("data_classification", sa.String(length=32), nullable=False),
        sa.Column("snapshot_checksum", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "review_id",
            "source_record_id",
            name="uq_published_snapshot_review_record",
        ),
    )
    for column in (
        "review_id",
        "dataset_id",
        "run_id",
        "scenario_id",
        "release_version",
        "station_id",
        "region_id",
    ):
        op.create_index(
            f"ix_published_station_snapshot_{column}",
            "published_station_snapshot",
            [column],
        )


def downgrade() -> None:
    op.drop_table("published_station_snapshot")
    op.drop_table("scenario_package_release")
