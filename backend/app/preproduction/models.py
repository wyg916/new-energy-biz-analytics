from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class PreproductionAcceptanceRecord(Base):
    __tablename__ = "preproduction_acceptance_record"
    __table_args__ = (
        UniqueConstraint("run_id", "category", name="uq_preproduction_acceptance_run_category"),
        Index("ix_preproduction_acceptance_status", "environment", "category", "status"),
    )

    acceptance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(96), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24))
    environment: Mapped[str] = mapped_column(String(32), default="preproduction", index=True)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_hash: Mapped[str] = mapped_column(String(64))
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PreproductionDataSourceGovernance(Base):
    __tablename__ = "preproduction_datasource_governance"
    __table_args__ = (
        UniqueConstraint("source_id", name="uq_p4_datasource_governance_source"),
        Index("ix_p4_datasource_governance_scope", "tenant_id", "workspace_id", "lifecycle_status"),
    )

    governance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_source_connection.source_id"), index=True)
    credential_ref_id: Mapped[str] = mapped_column(ForeignKey("credential_reference.credential_ref_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated", index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(24), default="DRAFT", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExternalAlertDelivery(Base):
    __tablename__ = "external_alert_delivery"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_external_alert_delivery_idempotency"),
        Index("ix_external_alert_delivery_status", "status", "created_at"),
    )

    delivery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("security_alert.alert_id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(24))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    endpoint_hash: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(96), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


P4_PREPRODUCTION_TABLES = (
    PreproductionAcceptanceRecord.__table__,
    PreproductionDataSourceGovernance.__table__,
    ExternalAlertDelivery.__table__,
)
