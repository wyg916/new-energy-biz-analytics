from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Principal(Base):
    __tablename__ = "identity_principal"
    __table_args__ = (
        UniqueConstraint(
            "provider_code", "external_subject", "tenant_id",
            name="uq_identity_principal_provider_subject_tenant",
        ),
        Index("ix_identity_principal_scope_status", "tenant_id", "workspace_id", "status"),
    )

    principal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal_type: Mapped[str] = mapped_column(String(24), index=True)
    provider_code: Mapped[str] = mapped_column(String(64), index=True)
    external_subject: Mapped[str] = mapped_column(String(256))
    local_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), index=True)
    auth_strength: Mapped[str] = mapped_column(String(32))
    attributes_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdentityGroup(Base):
    __tablename__ = "identity_group"
    __table_args__ = (
        UniqueConstraint("tenant_id", "workspace_id", "group_code", name="uq_identity_group_scope_code"),
    )

    group_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    group_code: Mapped[str] = mapped_column(String(96), index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IdentityGroupMembership(Base):
    __tablename__ = "identity_group_membership"
    __table_args__ = (
        UniqueConstraint("principal_id", "group_id", name="uq_identity_group_member"),
        Index("ix_identity_group_membership_scope", "tenant_id", "workspace_id", "status"),
    )

    membership_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("identity_principal.principal_id"), index=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("identity_group.group_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GovernanceRole(Base):
    __tablename__ = "governance_role"
    __table_args__ = (
        UniqueConstraint("tenant_id", "role_code", name="uq_governance_role_tenant_code"),
    )

    role_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    role_code: Mapped[str] = mapped_column(String(96), index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), index=True)
    system_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GovernancePermission(Base):
    __tablename__ = "governance_permission"

    permission_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    permission_code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(96), index=True)
    description: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GovernanceRolePermission(Base):
    __tablename__ = "governance_role_permission"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_governance_role_permission"),
    )

    role_permission_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("governance_role.role_id"), index=True)
    permission_id: Mapped[str] = mapped_column(ForeignKey("governance_permission.permission_id"), index=True)
    effect: Mapped[str] = mapped_column(String(16), default="ALLOW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GovernancePolicy(Base):
    __tablename__ = "governance_policy"
    __table_args__ = (
        UniqueConstraint("tenant_id", "policy_code", "version", name="uq_governance_policy_version"),
        Index("ix_governance_policy_scope_status", "tenant_id", "workspace_id", "status"),
    )

    policy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    policy_code: Mapped[str] = mapped_column(String(96), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), index=True)
    effect: Mapped[str] = mapped_column(String(16))
    actions_json: Mapped[str] = mapped_column(Text)
    resource_types_json: Mapped[str] = mapped_column(Text)
    conditions_json: Mapped[str] = mapped_column(Text, default="{}")
    approved_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GovernanceBinding(Base):
    __tablename__ = "governance_binding"
    __table_args__ = (
        CheckConstraint(
            "principal_id IS NOT NULL OR group_id IS NOT NULL OR role_id IS NOT NULL",
            name="ck_governance_binding_subject",
        ),
        CheckConstraint(
            "role_id IS NOT NULL OR policy_id IS NOT NULL",
            name="ck_governance_binding_target",
        ),
        Index("ix_governance_binding_scope_status", "tenant_id", "workspace_id", "status"),
    )

    binding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    principal_id: Mapped[str | None] = mapped_column(ForeignKey("identity_principal.principal_id"), nullable=True, index=True)
    group_id: Mapped[str | None] = mapped_column(ForeignKey("identity_group.group_id"), nullable=True, index=True)
    role_id: Mapped[str | None] = mapped_column(ForeignKey("governance_role.role_id"), nullable=True, index=True)
    policy_id: Mapped[str | None] = mapped_column(ForeignKey("governance_policy.policy_id"), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), default="*")
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment: Mapped[str] = mapped_column(String(32), default="development")
    status: Mapped[str] = mapped_column(String(24), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CredentialReference(Base):
    __tablename__ = "credential_reference"
    __table_args__ = (
        UniqueConstraint("tenant_id", "workspace_id", "reference_name", "version", name="uq_credential_reference_version"),
        Index("ix_credential_reference_scope_status", "tenant_id", "workspace_id", "status"),
    )

    credential_ref_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reference_name: Mapped[str] = mapped_column(String(96), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    secret_identifier: Mapped[str] = mapped_column(String(160))
    purpose: Mapped[str] = mapped_column(String(128))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    environment: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    version: Mapped[int] = mapped_column(Integer)
    allowed_actions_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    rotated_from_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CredentialUsageAudit(Base):
    __tablename__ = "credential_usage_audit"
    __table_args__ = (
        Index("ix_credential_usage_scope_created", "tenant_id", "workspace_id", "created_at"),
    )

    usage_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    credential_ref_id: Mapped[str] = mapped_column(ForeignKey("credential_reference.credential_ref_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_subject_id: Mapped[str] = mapped_column(String(96), index=True)
    action: Mapped[str] = mapped_column(String(96), index=True)
    outcome: Mapped[str] = mapped_column(String(24), index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(96), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RetentionPolicy(Base):
    __tablename__ = "retention_policy"
    __table_args__ = (
        UniqueConstraint("tenant_id", "workspace_id", "policy_code", "version", name="uq_retention_policy_version"),
        Index("ix_retention_policy_scope_status", "tenant_id", "workspace_id", "status"),
    )

    retention_policy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_code: Mapped[str] = mapped_column(String(96), index=True)
    version: Mapped[int] = mapped_column(Integer)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(32), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    memory_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    retention_days: Mapped[int] = mapped_column(Integer)
    archive_after_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deletion_mode: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), index=True)
    approved_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LegalHold(Base):
    __tablename__ = "legal_hold"
    __table_args__ = (
        Index("ix_legal_hold_scope_status", "tenant_id", "workspace_id", "status"),
        Index("ix_legal_hold_resource", "resource_type", "resource_id", "status"),
    )

    legal_hold_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(32), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    memory_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    reason_code: Mapped[str] = mapped_column(String(96))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24), index=True)
    created_by: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    released_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class GovernanceAuditEvent(Base):
    __tablename__ = "governance_audit_event"
    __table_args__ = (
        Index("ix_governance_audit_scope_created", "tenant_id", "workspace_id", "created_at"),
        Index("ix_governance_audit_actor_action", "actor_subject_id", "action", "created_at"),
        Index("ix_governance_audit_resource", "resource_type", "resource_id", "created_at"),
        Index("ix_governance_audit_trace", "trace_id", "created_at"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_subject_id: Mapped[str] = mapped_column(String(96), index=True)
    principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(96), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    result: Mapped[str] = mapped_column(String(24), index=True)
    trace_id: Mapped[str] = mapped_column(String(96), index=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class SecurityAlert(Base):
    __tablename__ = "security_alert"
    __table_args__ = (
        Index("ix_security_alert_scope_status", "tenant_id", "workspace_id", "status", "last_seen_at"),
        UniqueConstraint("tenant_id", "workspace_id", "rule_code", "correlation_key", "status", name="uq_security_alert_open_correlation"),
    )

    alert_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_code: Mapped[str] = mapped_column(String(96), index=True)
    correlation_key: Mapped[str] = mapped_column(String(160))
    severity: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    event_count: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(String(500))
    trace_id: Mapped[str] = mapped_column(String(96), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    acknowledged_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformRelease(Base):
    __tablename__ = "platform_release"
    __table_args__ = (
        UniqueConstraint("tenant_id", "workspace_id", "object_type", "object_id", "version", "environment", name="uq_platform_release_version"),
        Index("ix_platform_release_scope_status", "tenant_id", "workspace_id", "status"),
        Index("ix_platform_release_object", "object_type", "object_id", "environment"),
    )

    release_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    object_type: Mapped[str] = mapped_column(String(64), index=True)
    object_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(48))
    environment: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    artifact_hash: Mapped[str] = mapped_column(String(64))
    change_summary: Mapped[str] = mapped_column(String(500))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[str] = mapped_column(String(96))
    reviewed_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    activated_by: Mapped[str | None] = mapped_column(String(96), nullable=True)
    supersedes_release_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rollback_of_release_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


P3_GOVERNANCE_TABLES = [
    Principal.__table__,
    IdentityGroup.__table__,
    IdentityGroupMembership.__table__,
    GovernanceRole.__table__,
    GovernancePermission.__table__,
    GovernanceRolePermission.__table__,
    GovernancePolicy.__table__,
    GovernanceBinding.__table__,
    CredentialReference.__table__,
    CredentialUsageAudit.__table__,
    RetentionPolicy.__table__,
    LegalHold.__table__,
    GovernanceAuditEvent.__table__,
    SecurityAlert.__table__,
    PlatformRelease.__table__,
]


@event.listens_for(GovernanceAuditEvent, "before_update")
@event.listens_for(GovernanceAuditEvent, "before_delete")
def _governance_audit_is_immutable(*_args) -> None:
    raise RuntimeError("governance audit events are immutable")
