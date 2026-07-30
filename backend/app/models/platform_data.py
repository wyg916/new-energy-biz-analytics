from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class PlatformDataset(Base):
    __tablename__ = "dataset"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "workspace_id", "scenario_id", "code",
            name="uq_dataset_scope_code",
        ),
    )

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(160))
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_source_connection.source_id"), nullable=True, index=True
    )
    owner_subject_id: Mapped[str] = mapped_column(String(96))
    data_classification: Mapped[str] = mapped_column(String(32), default="unclassified")
    status: Mapped[str] = mapped_column(String(24), default="ENABLED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MappingVersion(Base):
    __tablename__ = "mapping_version"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version", name="uq_mapping_version"),
        UniqueConstraint("dataset_id", "checksum", name="uq_mapping_checksum"),
    )

    mapping_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.dataset_id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    mapping_json: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", index=True)
    created_by: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QualityResult(Base):
    __tablename__ = "quality_result"
    __table_args__ = (
        UniqueConstraint("dataset_id", "run_id", name="uq_quality_dataset_run"),
    )

    quality_result_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.dataset_id"), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    rules_json: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))
    checked_by: Mapped[str] = mapped_column(String(96))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DatasetVersion(Base):
    __tablename__ = "dataset_version"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),
        UniqueConstraint("dataset_id", "idempotency_key", name="uq_dataset_version_idempotency"),
        Index(
            "uq_dataset_single_active",
            "dataset_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    dataset_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.dataset_id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", index=True)
    schema_json: Mapped[str] = mapped_column(Text)
    source_binding_json: Mapped[str] = mapped_column(Text)
    source_version: Mapped[str] = mapped_column(String(128))
    mapping_version_id: Mapped[str] = mapped_column(ForeignKey("mapping_version.mapping_version_id"))
    quality_result_id: Mapped[str] = mapped_column(ForeignKey("quality_result.quality_result_id"))
    checksum: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period_end_exclusive: Mapped[str | None] = mapped_column(String(32), nullable=True)
    compatible_semantic_range: Mapped[str] = mapped_column(String(64), default="*")
    idempotency_key: Mapped[str] = mapped_column(String(96))
    created_by: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewRecord(Base):
    __tablename__ = "review_record"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", name="uq_review_dataset_version"),
    )

    review_record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_version.dataset_version_id"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    requested_by: Mapped[str] = mapped_column(String(96))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ReleaseRecord(Base):
    __tablename__ = "release_record"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_release_idempotency"),
    )

    release_record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.dataset_id"), index=True)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_version.dataset_version_id"), index=True
    )
    action: Mapped[str] = mapped_column(String(32), index=True)
    outcome: Mapped[str] = mapped_column(String(24))
    actor_subject_id: Mapped[str] = mapped_column(String(96))
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SemanticActivation(Base):
    __tablename__ = "semantic_activation"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "workspace_id", "scenario_id", "dataset_id",
            name="uq_semantic_activation_scope",
        ),
    )

    activation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    scenario_version: Mapped[str] = mapped_column(String(32))
    dataset_id: Mapped[str] = mapped_column(ForeignKey("dataset.dataset_id"), index=True)
    active_dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_version.dataset_version_id"), index=True
    )
    active_semantic_model_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    activated_by: Mapped[str] = mapped_column(String(96))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RollbackRecord(Base):
    __tablename__ = "rollback_record"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_rollback_idempotency"),
    )

    rollback_record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    activation_id: Mapped[str] = mapped_column(
        ForeignKey("semantic_activation.activation_id"), index=True
    )
    from_dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_version.dataset_version_id")
    )
    to_dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_version.dataset_version_id")
    )
    reason: Mapped[str] = mapped_column(String(500))
    actor_subject_id: Mapped[str] = mapped_column(String(96))
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


DATASET_TABLES = [
    PlatformDataset.__table__,
    MappingVersion.__table__,
    QualityResult.__table__,
    DatasetVersion.__table__,
    ReviewRecord.__table__,
    ReleaseRecord.__table__,
    SemanticActivation.__table__,
    RollbackRecord.__table__,
]

