from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryRecord(Base):
    __tablename__ = "memory_record"
    __table_args__ = (
        Index(
            "ix_memory_record_scope_lookup",
            "tenant_id",
            "workspace_id",
            "user_id",
            "scenario_id",
            "memory_type",
            "status",
        ),
        Index("ix_memory_record_session", "session_id", "status"),
        Index("ix_memory_record_run", "run_id", "status"),
        UniqueConstraint("duplicate_hash", "version", name="uq_memory_duplicate_version"),
    )

    memory_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(24), index=True)
    scope_type: Mapped[str] = mapped_column(String(24), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    structured_value_json: Mapped[str] = mapped_column(Text, default="{}")
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trust_level: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    duplicate_hash: Mapped[str] = mapped_column(String(64), index=True)
    conflict_group: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    retention_policy: Mapped[str] = mapped_column(String(32), default="STANDARD")
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    recall_count: Mapped[int] = mapped_column(Integer, default=0)
    last_recalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    lifecycle_transition_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryWriteCandidateRecord(Base):
    __tablename__ = "memory_write_candidate"
    __table_args__ = (
        Index(
            "ix_memory_candidate_scope_status",
            "tenant_id",
            "workspace_id",
            "user_id",
            "scenario_id",
            "status",
        ),
        UniqueConstraint("idempotency_key", name="uq_memory_candidate_idempotency"),
    )

    candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(24), index=True)
    scope_type: Mapped[str] = mapped_column(String(24), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    structured_value_json: Mapped[str] = mapped_column(Text, default="{}")
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trust_level: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    duplicate_hash: Mapped[str] = mapped_column(String(64), index=True)
    conflict_group: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    data_classification: Mapped[str] = mapped_column(String(32), default="internal")
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_policy: Mapped[str] = mapped_column(String(32), default="STANDARD")
    write_reason: Mapped[str] = mapped_column(String(256))
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="CANDIDATE", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(96), nullable=True)


class MemoryAuditEvent(Base):
    __tablename__ = "memory_audit_event"
    __table_args__ = (
        Index("ix_memory_audit_scope_created", "tenant_id", "workspace_id", "created_at"),
        Index("ix_memory_audit_memory", "memory_id", "created_at"),
    )

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_subject_id: Mapped[str] = mapped_column(String(96), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(32))
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MemoryDeletionAudit(Base):
    __tablename__ = "memory_deletion_audit"
    __table_args__ = (
        Index("ix_memory_deletion_scope", "tenant_id", "workspace_id", "user_id", "created_at"),
    )

    deletion_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_id_hash: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    requested_by: Mapped[str] = mapped_column(String(96))
    deletion_mode: Mapped[str] = mapped_column(String(32))
    derived_index_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    working_memory_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    legal_hold_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MemoryLifecycleTask(Base):
    __tablename__ = "memory_lifecycle_task"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_memory_lifecycle_task_idempotency"),
        Index("ix_memory_lifecycle_task_due", "status", "next_attempt_at", "created_at"),
        Index("ix_memory_lifecycle_task_scope", "tenant_id", "workspace_id", "task_type", "created_at"),
    )

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    requested_by: Mapped[str] = mapped_column(String(96), index=True)
    memory_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(String(500))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    idempotency_key: Mapped[str] = mapped_column(String(160))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    locked_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryLifecycleOutbox(Base):
    __tablename__ = "memory_lifecycle_outbox"
    __table_args__ = (
        UniqueConstraint("task_id", "target_store", "operation", "resource_id", name="uq_memory_outbox_delivery"),
        Index("ix_memory_outbox_due", "status", "next_attempt_at", "created_at"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("memory_lifecycle_task.task_id"), index=True)
    operation: Mapped[str] = mapped_column(String(32))
    target_store: Mapped[str] = mapped_column(String(24), index=True)
    resource_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryDeleteVerification(Base):
    __tablename__ = "memory_delete_verification"
    __table_args__ = (
        UniqueConstraint("task_id", "target_store", name="uq_memory_delete_verification_store"),
        Index("ix_memory_delete_verification_task", "task_id", "checked_at"),
    )

    verification_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("memory_lifecycle_task.task_id"), index=True)
    target_store: Mapped[str] = mapped_column(String(24))
    resource_id_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), index=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProcedureDefinition(Base):
    __tablename__ = "procedure_definition"
    __table_args__ = (
        UniqueConstraint("procedure_code", "version", name="uq_procedure_code_version"),
        Index("ix_procedure_status_scenario", "status", "scenario_id"),
    )

    procedure_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    procedure_code: Mapped[str] = mapped_column(String(96), index=True)
    version: Mapped[str] = mapped_column(String(32))
    scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    owner_subject_id: Mapped[str] = mapped_column(String(96))
    input_schema_json: Mapped[str] = mapped_column(Text)
    output_schema_json: Mapped[str] = mapped_column(Text)
    steps_json: Mapped[str] = mapped_column(Text)
    branches_json: Mapped[str] = mapped_column(Text, default="[]")
    validations_json: Mapped[str] = mapped_column(Text, default="[]")
    failure_policy_json: Mapped[str] = mapped_column(Text, default="{}")
    test_manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    rollout_json: Mapped[str] = mapped_column(Text, default="{}")
    rollback_procedure_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SkillDefinition(Base):
    __tablename__ = "skill_definition"
    __table_args__ = (
        UniqueConstraint("skill_code", "version", "scenario_id", name="uq_skill_code_version_scenario"),
        Index("ix_skill_status_scenario", "status", "scenario_id"),
    )

    skill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    skill_code: Mapped[str] = mapped_column(String(96), index=True)
    version: Mapped[str] = mapped_column(String(32))
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    procedure_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    owner_subject_id: Mapped[str] = mapped_column(String(96))
    adapter_code: Mapped[str] = mapped_column(String(96))
    input_schema_json: Mapped[str] = mapped_column(Text)
    output_schema_json: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    shadow_result_json: Mapped[str] = mapped_column(Text, default="{}")
    rollback_skill_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SkillExecutionRecord(Base):
    __tablename__ = "skill_execution"
    __table_args__ = (
        Index("ix_skill_execution_scope_run", "tenant_id", "workspace_id", "run_id"),
        Index("ix_skill_execution_skill_created", "skill_id", "created_at"),
    )

    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(96), index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    trace_id: Mapped[str] = mapped_column(String(96), index=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    input_json: Mapped[str] = mapped_column(Text)
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SQLBotSourceBindingRelease(Base):
    __tablename__ = "sqlbot_source_binding_release"
    __table_args__ = (
        UniqueConstraint("scenario_id", "version", name="uq_sqlbot_binding_scenario_version"),
        Index("ix_sqlbot_binding_active", "scenario_id", "status"),
        Index(
            "uq_sqlbot_binding_single_active",
            "scenario_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    binding_release_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    datasource_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), index=True)
    binding_json: Mapped[str] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_of_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


P2B_MEMORY_TABLES = [
    MemoryRecord.__table__,
    MemoryWriteCandidateRecord.__table__,
    MemoryAuditEvent.__table__,
    MemoryDeletionAudit.__table__,
    ProcedureDefinition.__table__,
    SkillDefinition.__table__,
    SkillExecutionRecord.__table__,
    SQLBotSourceBindingRelease.__table__,
]


MEMORY_LIFECYCLE_TABLES = [
    MemoryLifecycleTask.__table__,
    MemoryLifecycleOutbox.__table__,
    MemoryDeleteVerification.__table__,
]
