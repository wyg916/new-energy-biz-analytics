from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class DataSourceConnection(Base):
    __tablename__ = "data_source_connection"

    source_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    source_type: Mapped[str] = mapped_column(String(16), index=True)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    database_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    credential_env_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    connection_options_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(24), default="configured", index=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DataSetDefinition(Base):
    __tablename__ = "data_set_definition"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_source_connection.source_id"), index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    source_object: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_table: Mapped[str] = mapped_column(String(128))
    standard_schema: Mapped[str] = mapped_column(String(64), default="charging_ops")
    mapping_json: Mapped[str] = mapped_column(Text)
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DataIngestionRun(Base):
    __tablename__ = "data_ingestion_run"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("data_set_definition.dataset_id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_source_connection.source_id"), index=True)
    trigger_type: Mapped[str] = mapped_column(String(24), default="manual")
    status: Mapped[str] = mapped_column(String(24), index=True)
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    source_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestedStationPreview(Base):
    __tablename__ = "ingested_station_preview"
    __table_args__ = (UniqueConstraint("dataset_id", "source_record_id", name="uq_ingested_station_preview_record"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("data_set_definition.dataset_id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_source_connection.source_id"), index=True)
    source_record_id: Mapped[str] = mapped_column(String(128))
    station_id: Mapped[str] = mapped_column(String(32), index=True)
    station_name: Mapped[str] = mapped_column(String(128))
    region_id: Mapped[str] = mapped_column(String(32), index=True)
    city_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    charging_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    charging_volume_kwh: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    gross_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    gross_margin: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    batch_id: Mapped[str] = mapped_column(String(64), index=True)
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
