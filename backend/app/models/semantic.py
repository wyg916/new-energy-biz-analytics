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


class SemanticModel(Base):
    __tablename__ = "semantic_model"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "workspace_id", "scenario_id", "code",
            name="uq_semantic_model_scope_code",
        ),
    )

    semantic_model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(160))
    owner_subject_id: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(24), default="ENABLED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SemanticModelVersion(Base):
    __tablename__ = "semantic_model_version"
    __table_args__ = (
        UniqueConstraint("semantic_model_id", "version", name="uq_semantic_model_version"),
        UniqueConstraint("semantic_model_id", "checksum", name="uq_semantic_model_checksum"),
        Index(
            "uq_semantic_model_single_active",
            "semantic_model_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    semantic_model_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    semantic_model_id: Mapped[str] = mapped_column(
        ForeignKey("semantic_model.semantic_model_id"), index=True
    )
    version: Mapped[str] = mapped_column(String(32))
    scenario_version: Mapped[str] = mapped_column(String(32))
    contract_version: Mapped[str] = mapped_column(String(32))
    dataset_compatibility_json: Mapped[str] = mapped_column(Text)
    model_json: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", index=True)
    created_by: Mapped[str] = mapped_column(String(96))
    reviewed_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SemanticTable(Base):
    __tablename__ = "semantic_table"
    __table_args__ = (
        UniqueConstraint("semantic_model_version_id", "code", name="uq_semantic_table_code"),
    )

    semantic_table_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    semantic_model_version_id: Mapped[str] = mapped_column(
        ForeignKey("semantic_model_version.semantic_model_version_id"), index=True
    )
    code: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(160))
    physical_binding: Mapped[str] = mapped_column(String(256))
    grain_json: Mapped[str] = mapped_column(Text)
    lineage_json: Mapped[str] = mapped_column(Text)


class SemanticField(Base):
    __tablename__ = "semantic_field"
    __table_args__ = (
        UniqueConstraint("semantic_table_id", "code", name="uq_semantic_field_code"),
    )

    semantic_field_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    semantic_table_id: Mapped[str] = mapped_column(
        ForeignKey("semantic_table.semantic_table_id"), index=True
    )
    code: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(160))
    data_type: Mapped[str] = mapped_column(String(32))
    physical_field: Mapped[str] = mapped_column(String(128))
    nullable: Mapped[int] = mapped_column(Integer, default=1)
    classification: Mapped[str] = mapped_column(String(32), default="internal")
    permission_policy_json: Mapped[str] = mapped_column(Text, default="{}")
    lineage_json: Mapped[str] = mapped_column(Text, default="{}")


class SemanticMetric(Base):
    __tablename__ = "metric"
    __table_args__ = (
        UniqueConstraint("semantic_model_version_id", "code", name="uq_metric_version_code"),
    )

    metric_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    semantic_model_version_id: Mapped[str] = mapped_column(
        ForeignKey("semantic_model_version.semantic_model_version_id"), index=True
    )
    code: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(160))
    aliases_json: Mapped[str] = mapped_column(Text)
    expression: Mapped[str] = mapped_column(Text)
    aggregation: Mapped[str] = mapped_column(String(32))
    grain_json: Mapped[str] = mapped_column(Text)
    time_field: Mapped[str | None] = mapped_column(String(96), nullable=True)
    supported_dimensions_json: Mapped[str] = mapped_column(Text)
    filters_json: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32))
    format: Mapped[str] = mapped_column(String(64))
    owner: Mapped[str] = mapped_column(String(96))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    permission_policy_json: Mapped[str] = mapped_column(Text)
    lineage_json: Mapped[str] = mapped_column(Text)


class SemanticDimension(Base):
    __tablename__ = "dimension"
    __table_args__ = (
        UniqueConstraint("semantic_model_version_id", "code", name="uq_dimension_version_code"),
    )

    dimension_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    semantic_model_version_id: Mapped[str] = mapped_column(
        ForeignKey("semantic_model_version.semantic_model_version_id"), index=True
    )
    code: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(160))
    aliases_json: Mapped[str] = mapped_column(Text)
    field_ref: Mapped[str] = mapped_column(String(192))
    data_type: Mapped[str] = mapped_column(String(32))
    hierarchy_json: Mapped[str] = mapped_column(Text)
    permission_policy_json: Mapped[str] = mapped_column(Text)
    lineage_json: Mapped[str] = mapped_column(Text)


class SemanticRelationship(Base):
    __tablename__ = "relationship"
    __table_args__ = (
        UniqueConstraint(
            "semantic_model_version_id", "code",
            name="uq_relationship_version_code",
        ),
    )

    relationship_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    semantic_model_version_id: Mapped[str] = mapped_column(
        ForeignKey("semantic_model_version.semantic_model_version_id"), index=True
    )
    code: Mapped[str] = mapped_column(String(96))
    source_table: Mapped[str] = mapped_column(String(96))
    source_fields_json: Mapped[str] = mapped_column(Text)
    target_table: Mapped[str] = mapped_column(String(96))
    target_fields_json: Mapped[str] = mapped_column(Text)
    cardinality: Mapped[str] = mapped_column(String(32))
    join_type: Mapped[str] = mapped_column(String(16), default="inner")
    status: Mapped[str] = mapped_column(String(24), default="PUBLISHED")


class SemanticTimeDimension(Base):
    __tablename__ = "time_dimension"
    __table_args__ = (
        UniqueConstraint(
            "semantic_model_version_id", "code",
            name="uq_time_dimension_version_code",
        ),
    )

    time_dimension_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    semantic_model_version_id: Mapped[str] = mapped_column(
        ForeignKey("semantic_model_version.semantic_model_version_id"), index=True
    )
    code: Mapped[str] = mapped_column(String(96))
    field_ref: Mapped[str] = mapped_column(String(192))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    grains_json: Mapped[str] = mapped_column(Text)
    fiscal_calendar_json: Mapped[str] = mapped_column(Text, default="{}")


class SemanticFilter(Base):
    __tablename__ = "semantic_filter"
    __table_args__ = (
        UniqueConstraint(
            "semantic_model_version_id", "code",
            name="uq_semantic_filter_version_code",
        ),
    )

    semantic_filter_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    semantic_model_version_id: Mapped[str] = mapped_column(
        ForeignKey("semantic_model_version.semantic_model_version_id"), index=True
    )
    code: Mapped[str] = mapped_column(String(96))
    expression_json: Mapped[str] = mapped_column(Text)
    required: Mapped[int] = mapped_column(Integer, default=0)
    permission_policy_json: Mapped[str] = mapped_column(Text, default="{}")


class DataPolicy(Base):
    __tablename__ = "data_policy"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "workspace_id", "semantic_model_version_id", "code",
            name="uq_data_policy_scope_code",
        ),
    )

    data_policy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    semantic_model_version_id: Mapped[str] = mapped_column(
        ForeignKey("semantic_model_version.semantic_model_version_id"), index=True
    )
    code: Mapped[str] = mapped_column(String(96))
    roles_json: Mapped[str] = mapped_column(Text)
    row_filter_json: Mapped[str] = mapped_column(Text)
    column_masks_json: Mapped[str] = mapped_column(Text)
    export_allowed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="PUBLISHED")


SEMANTIC_TABLES = [
    SemanticModel.__table__,
    SemanticModelVersion.__table__,
    SemanticTable.__table__,
    SemanticField.__table__,
    SemanticMetric.__table__,
    SemanticDimension.__table__,
    SemanticRelationship.__table__,
    SemanticTimeDimension.__table__,
    SemanticFilter.__table__,
    DataPolicy.__table__,
]

