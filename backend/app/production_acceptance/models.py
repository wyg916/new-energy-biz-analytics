from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProductionGate(Base):
    __tablename__ = "production_gate_registry"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "workspace_id", "environment", "gate_code",
            name="uq_production_gate_scope_code",
        ),
        Index(
            "ix_production_gate_status",
            "tenant_id", "workspace_id", "environment", "status",
        ),
    )

    gate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    gate_code: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    environment: Mapped[str] = mapped_column(String(32), default="production", index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    owner_role: Mapped[str] = mapped_column(String(96))
    blocker_level: Mapped[str] = mapped_column(String(24), index=True)
    external_condition: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_requirement: Mapped[str] = mapped_column(String(500))
    waiver_approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    waiver_basis: Mapped[str | None] = mapped_column(String(500), nullable=True)
    waiver_evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProductionGateHistory(Base):
    __tablename__ = "production_gate_history"
    __table_args__ = (
        Index("ix_production_gate_history_gate", "gate_id", "created_at"),
        Index("ix_production_gate_history_scope", "tenant_id", "workspace_id", "created_at"),
    )

    history_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    gate_id: Mapped[str] = mapped_column(ForeignKey("production_gate_registry.gate_id"), index=True)
    gate_code: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(String(500))
    actor_subject_id: Mapped[str] = mapped_column(String(96))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


P5_PRODUCTION_ACCEPTANCE_TABLES = (
    ProductionGate.__table__,
    ProductionGateHistory.__table__,
)


@event.listens_for(ProductionGateHistory, "before_update")
@event.listens_for(ProductionGateHistory, "before_delete")
def _production_gate_history_is_immutable(*_args) -> None:
    raise RuntimeError("production gate history is immutable")
