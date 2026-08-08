from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class OpenDataSource(Base):
    __tablename__ = "open_data_source"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(Text)
    source_identifier: Mapped[str] = mapped_column(String(160), unique=True)
    license_name: Mapped[str] = mapped_column(String(96))
    publisher: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(24), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OpenDataSnapshot(Base):
    __tablename__ = "open_data_snapshot"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("open_data_source.source_id"), index=True)
    dataset_version: Mapped[str] = mapped_column(String(128), index=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64), unique=True)
    source_row_count: Mapped[int] = mapped_column(Integer)
    snapshot_row_count: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    local_path: Mapped[str] = mapped_column(String(240))
    selection_method: Mapped[str] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OpenDataIngestionRun(Base):
    __tablename__ = "open_data_ingestion_run"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("open_data_source.source_id"), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("open_data_snapshot.snapshot_id"), index=True)
    transformation_version: Mapped[str] = mapped_column(String(96))
    ingestion_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    raw_row_count: Mapped[int] = mapped_column(Integer)
    staging_row_count: Mapped[int] = mapped_column(Integer)
    core_row_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), index=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class OpenDataQualityCheck(Base):
    __tablename__ = "open_data_quality_check"
    __table_args__ = (
        UniqueConstraint("run_id", "check_name", name="uq_open_data_quality_run_check"),
    )

    quality_check_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("open_data_ingestion_run.run_id"), index=True)
    check_name: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(16), index=True)
    observed_value: Mapped[str] = mapped_column(Text)
    expected_value: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RawAcnSession(Base):
    __tablename__ = "raw_acn_session"
    __table_args__ = (UniqueConstraint("run_id", "source_record_id", name="uq_raw_acn_run_record"),)

    raw_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("open_data_ingestion_run.run_id"), index=True)
    source_record_id: Mapped[str] = mapped_column(String(96))
    source_row_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)


class StagingAcnSession(Base):
    __tablename__ = "stg_acn_session"

    session_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("open_data_ingestion_run.run_id"), index=True)
    source_record_id: Mapped[str] = mapped_column(String(96), index=True)
    site_id: Mapped[str] = mapped_column(String(32))
    station_id: Mapped[str] = mapped_column(String(64), index=True)
    space_id: Mapped[str] = mapped_column(String(64))
    source_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    connection_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    disconnect_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    done_charging_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    energy_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    payment_required: Mapped[int] = mapped_column(Integer)
    source_row_hash: Mapped[str] = mapped_column(String(64))


class RawUciRetailLine(Base):
    __tablename__ = "raw_uci_retail_line"
    __table_args__ = (UniqueConstraint("run_id", "source_row_number", name="uq_raw_uci_run_row"),)

    raw_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("open_data_ingestion_run.run_id"), index=True)
    source_row_number: Mapped[int] = mapped_column(Integer)
    source_row_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)


class StagingUciRetailLine(Base):
    __tablename__ = "stg_uci_retail_line"

    line_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("open_data_ingestion_run.run_id"), index=True)
    source_row_number: Mapped[int] = mapped_column(Integer)
    invoice_no: Mapped[str] = mapped_column(String(32), index=True)
    stock_code: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(String(240), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    invoice_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    customer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country: Mapped[str] = mapped_column(String(96), index=True)
    is_cancellation: Mapped[int] = mapped_column(Integer, index=True)
    source_row_hash: Mapped[str] = mapped_column(String(64))


OPEN_DATA_TABLES = [
    OpenDataSource.__table__,
    OpenDataSnapshot.__table__,
    OpenDataIngestionRun.__table__,
    OpenDataQualityCheck.__table__,
    RawAcnSession.__table__,
    StagingAcnSession.__table__,
    RawUciRetailLine.__table__,
    StagingUciRetailLine.__table__,
]
