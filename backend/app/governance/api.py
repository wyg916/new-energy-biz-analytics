from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import trusted_identity
from app.core.config import get_settings
from app.core.database import get_db
from app.core.observability import readiness_snapshot
from app.governance.audit import GovernanceAuditQuery, record_governance_event
from app.governance.authorization import AuthorizationDenied, AuthorizationService, request_context
from app.governance.contracts import CredentialStatus
from app.governance.models import (
    CredentialReference,
    CredentialUsageAudit,
    GovernanceAuditEvent,
    GovernanceBinding,
    GovernancePermission,
    GovernancePolicy,
    GovernanceRole,
    IdentityGroup,
    LegalHold,
    PlatformRelease,
    Principal,
    RetentionPolicy,
    SecurityAlert,
)
from app.governance.policy import PolicyGovernanceError, PolicyGovernanceService
from app.governance.release import ReleaseGovernanceError, ReleaseRegistry
from app.governance.retention import LegalHoldService, RetentionError, RetentionPolicyService
from app.governance.secrets import CredentialReferenceService, SecretResolutionError
from app.platform.identity import IdentityContext
from app.memory.models import ProcedureDefinition
from app.memory.procedural import ProcedureRegistry, ProcedureRegistryError
from app.memory.contracts import ProcedureStatus


router = APIRouter(prefix="/governance", tags=["governance"])


class PolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    effect: Literal["ALLOW", "DENY"]
    actions: list[str] = Field(min_length=1, max_length=64)
    resource_types: list[str] = Field(min_length=1, max_length=32)
    conditions: dict[str, Any] = Field(default_factory=dict)


class PolicyBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role_code: str = Field(min_length=2, max_length=96)
    scenario_id: str | None = Field(default=None, pattern=r"^(charging_ops|sales_ops)$")
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: str | None = Field(default=None, max_length=128)
    environment: Literal["development", "test", "staging"] = "development"


class CredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    provider: Literal["ENV"] = "ENV"
    secret_identifier: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    purpose: str = Field(min_length=3, max_length=128)
    scenario_id: str | None = Field(default=None, pattern=r"^(charging_ops|sales_ops)$")
    environment: Literal["development", "test", "staging"] = "development"
    allowed_actions: list[str] = Field(min_length=1, max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CredentialRotateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret_identifier: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class LegalHoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_type: Literal["tenant", "workspace", "user", "memory", "document", "run", "audit_event"]
    resource_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=96)
    memory_type: str | None = Field(default=None, max_length=32)
    reason_code: str = Field(min_length=2, max_length=96)
    reason: str = Field(min_length=3, max_length=500)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class RetentionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,95}$")
    resource_type: Literal["tenant", "workspace", "user", "memory", "document", "run", "audit_event", "governance_audit"]
    resource_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=96)
    memory_type: str | None = Field(default=None, max_length=32)
    retention_days: int = Field(ge=1, le=3650)
    archive_after_days: int | None = Field(default=None, ge=1, le=3650)
    deletion_mode: Literal["ANONYMIZE", "ARCHIVE", "DELETE"]


class ReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_type: Literal[
        "SCENARIO_PACKAGE", "SEMANTIC_MODEL", "RAG_DOCUMENT", "PROCEDURE",
        "SKILL", "SQLBOT_SOURCE_BINDING", "POLICY_BUNDLE",
    ]
    object_id: str = Field(min_length=2, max_length=128)
    version: str = Field(min_length=1, max_length=48)
    environment: Literal["development", "test", "staging", "production"]
    artifact_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    change_summary: str = Field(min_length=3, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RollbackRequest(BaseModel):
    target_release_id: str = Field(min_length=8, max_length=64)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AuthorizationDenied):
        return HTTPException(403, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(409, detail={"code": getattr(exc, "code", type(exc).__name__.upper()), "message": str(exc)})


def _require(
    db: Session,
    identity: IdentityContext,
    action: str,
    resource_type: str,
    *,
    resource_id: str | None = None,
    scenario_id: str | None = None,
) -> None:
    AuthorizationService(db, identity).require(request_context(
        identity,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        scenario_id=scenario_id,
        environment=get_settings().app_env,
    ))


def _credential_view(row: CredentialReference) -> dict:
    return {
        "credential_ref_id": row.credential_ref_id,
        "reference_name": row.reference_name,
        "provider": row.provider,
        "purpose": row.purpose,
        "scenario_id": row.scenario_id,
        "environment": row.environment,
        "status": row.status,
        "version": row.version,
        "allowed_actions": json.loads(row.allowed_actions_json),
        "metadata": json.loads(row.metadata_json),
        "rotated_from_id": row.rotated_from_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "secret_value_exposed": False,
    }


def _policy_view(row: GovernancePolicy) -> dict:
    return {
        "policy_id": row.policy_id,
        "policy_code": row.policy_code,
        "version": row.version,
        "status": row.status,
        "effect": row.effect,
        "actions": json.loads(row.actions_json),
        "resource_types": json.loads(row.resource_types_json),
        "conditions": json.loads(row.conditions_json),
        "approved_by": row.approved_by,
    }


def _release_view(row: PlatformRelease) -> dict:
    return {
        "release_id": row.release_id,
        "object_type": row.object_type,
        "object_id": row.object_id,
        "version": row.version,
        "environment": row.environment,
        "status": row.status,
        "artifact_hash": row.artifact_hash,
        "change_summary": row.change_summary,
        "approved_by": row.approved_by,
        "activated_by": row.activated_by,
        "supersedes_release_id": row.supersedes_release_id,
        "rollback_of_release_id": row.rollback_of_release_id,
        "created_at": row.created_at,
    }


def _procedure_view(row: ProcedureDefinition) -> dict:
    return {
        "procedure_id": row.procedure_id,
        "procedure_code": row.procedure_code,
        "version": row.version,
        "scenario_id": row.scenario_id,
        "status": row.status,
        "owner": row.owner_subject_id,
        "approved_by": row.approved_by,
        "rollback_procedure_id": row.rollback_procedure_id,
    }


@router.get("/snapshot")
def snapshot(
    db: Session = Depends(get_db),
    identity: IdentityContext = Depends(trusted_identity),
) -> dict:
    try:
        _require(db, identity, "audit.view", "audit")
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    scope = (
        identity.tenant_id,
        identity.workspace_id,
    )
    principals = list(db.scalars(select(Principal).where(
        Principal.tenant_id == scope[0], Principal.workspace_id == scope[1]
    ).order_by(Principal.display_name)).all())
    roles = list(db.scalars(select(GovernanceRole).where(
        GovernanceRole.tenant_id == scope[0]
    ).order_by(GovernanceRole.role_code)).all())
    policies = list(db.scalars(select(GovernancePolicy).where(
        GovernancePolicy.tenant_id == scope[0], GovernancePolicy.workspace_id == scope[1]
    ).order_by(GovernancePolicy.policy_code, desc(GovernancePolicy.version))).all())
    credentials = list(db.scalars(select(CredentialReference).where(
        CredentialReference.tenant_id == scope[0], CredentialReference.workspace_id == scope[1]
    ).order_by(CredentialReference.reference_name, desc(CredentialReference.version))).all())
    holds = list(db.scalars(select(LegalHold).where(
        LegalHold.tenant_id == scope[0], LegalHold.workspace_id == scope[1]
    ).order_by(desc(LegalHold.created_at))).all())
    retention = list(db.scalars(select(RetentionPolicy).where(
        RetentionPolicy.tenant_id == scope[0], RetentionPolicy.workspace_id == scope[1]
    ).order_by(RetentionPolicy.policy_code, desc(RetentionPolicy.version))).all())
    alerts = list(db.scalars(select(SecurityAlert).where(
        SecurityAlert.tenant_id == scope[0], SecurityAlert.workspace_id == scope[1]
    ).order_by(desc(SecurityAlert.last_seen_at)).limit(50)).all())
    releases = list(db.scalars(select(PlatformRelease).where(
        PlatformRelease.tenant_id == scope[0], PlatformRelease.workspace_id == scope[1]
    ).order_by(desc(PlatformRelease.created_at)).limit(100)).all())
    audits = list(db.scalars(select(GovernanceAuditEvent).where(
        GovernanceAuditEvent.tenant_id == scope[0], GovernanceAuditEvent.workspace_id == scope[1]
    ).order_by(desc(GovernanceAuditEvent.created_at)).limit(50)).all())
    readiness, readiness_status = readiness_snapshot()
    return {
        "identity": {
            "principal_id": identity.principal_id,
            "subject_id": identity.subject_id,
            "tenant_id": identity.tenant_id,
            "workspace_id": identity.workspace_id,
            "roles": identity.roles,
            "provider": identity.provider_code,
            "auth_strength": identity.auth_strength,
        },
        "principals": [{
            "principal_id": row.principal_id, "display_name": row.display_name,
            "provider": row.provider_code, "type": row.principal_type, "status": row.status,
        } for row in principals],
        "roles": [{"role_id": row.role_id, "role_code": row.role_code, "status": row.status} for row in roles],
        "policies": [_policy_view(row) for row in policies],
        "credentials": [_credential_view(row) for row in credentials],
        "legal_holds": [{
            "legal_hold_id": row.legal_hold_id, "resource_type": row.resource_type,
            "resource_id": row.resource_id, "status": row.status, "reason_code": row.reason_code,
            "created_at": row.created_at,
        } for row in holds],
        "retention_policies": [{
            "retention_policy_id": row.retention_policy_id, "policy_code": row.policy_code,
            "resource_type": row.resource_type, "retention_days": row.retention_days,
            "archive_after_days": row.archive_after_days, "status": row.status,
        } for row in retention],
        "alerts": [{
            "alert_id": row.alert_id, "rule_code": row.rule_code, "severity": row.severity,
            "status": row.status, "event_count": row.event_count, "summary": row.summary,
            "trace_id": row.trace_id, "last_seen_at": row.last_seen_at,
        } for row in alerts],
        "releases": [_release_view(row) for row in releases],
        "audit_events": [{
            "event_id": row.event_id, "actor": row.actor_subject_id, "action": row.action,
            "resource_type": row.resource_type, "resource_id": row.resource_id,
            "result": row.result, "trace_id": row.trace_id, "created_at": row.created_at,
        } for row in audits],
        "runtime": {
            "readiness_http_status": readiness_status,
            "readiness": readiness,
            "query_engine_mode": get_settings().effective_query_engine_mode,
            "sqlbot_engine_enabled": get_settings().sqlbot_engine_enabled,
            "sqlbot_canary_eligible": False,
            "production_release_enabled": False,
            "data_classification": "simulated",
        },
    }


@router.get("/identities")
def identities(db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        _require(db, identity, "identity.manage", "identity")
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    principals = list(db.scalars(select(Principal).where(
        Principal.tenant_id == identity.tenant_id, Principal.workspace_id == identity.workspace_id
    )).all())
    groups = list(db.scalars(select(IdentityGroup).where(
        IdentityGroup.tenant_id == identity.tenant_id, IdentityGroup.workspace_id == identity.workspace_id
    )).all())
    return {
        "principals": [{"principal_id": row.principal_id, "provider": row.provider_code, "display_name": row.display_name, "status": row.status} for row in principals],
        "groups": [{"group_id": row.group_id, "group_code": row.group_code, "display_name": row.display_name, "status": row.status} for row in groups],
    }


@router.get("/roles-permissions")
def roles_permissions(db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        _require(db, identity, "policy.manage", "policy")
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    roles = list(db.scalars(select(GovernanceRole).where(GovernanceRole.tenant_id == identity.tenant_id)).all())
    permissions = list(db.scalars(select(GovernancePermission).order_by(GovernancePermission.permission_code)).all())
    bindings = list(db.scalars(select(GovernanceBinding).where(
        GovernanceBinding.tenant_id == identity.tenant_id,
        GovernanceBinding.workspace_id == identity.workspace_id,
    )).all())
    return {
        "roles": [{"role_id": row.role_id, "role_code": row.role_code, "status": row.status} for row in roles],
        "permissions": [{"permission_id": row.permission_id, "permission_code": row.permission_code, "resource_type": row.resource_type} for row in permissions],
        "bindings": [{"binding_id": row.binding_id, "role_id": row.role_id, "policy_id": row.policy_id, "scenario_id": row.scenario_id, "resource_type": row.resource_type, "status": row.status} for row in bindings],
    }


@router.post("/policies")
def create_policy(payload: PolicyRequest, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _policy_view(PolicyGovernanceService(db, identity).create(**payload.model_dump()))
    except (PolicyGovernanceError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/policies/{policy_id}/submit-review")
def submit_policy(policy_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _policy_view(PolicyGovernanceService(db, identity).submit_review(policy_id))
    except (PolicyGovernanceError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/policies/{policy_id}/approve")
def approve_policy(policy_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _policy_view(PolicyGovernanceService(db, identity).approve(policy_id))
    except (PolicyGovernanceError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/policies/{policy_id}/activate")
def activate_policy(policy_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _policy_view(PolicyGovernanceService(db, identity).activate(policy_id))
    except (PolicyGovernanceError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/policies/{policy_id}/bindings")
def bind_policy(policy_id: str, payload: PolicyBindingRequest, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        row = PolicyGovernanceService(db, identity).bind(policy_id, **payload.model_dump())
        return {"binding_id": row.binding_id, "status": row.status, "policy_id": row.policy_id, "role_id": row.role_id}
    except (PolicyGovernanceError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.get("/credentials")
def credentials(db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        _require(db, identity, "credential.manage", "credential_reference")
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    rows = db.scalars(select(CredentialReference).where(
        CredentialReference.tenant_id == identity.tenant_id,
        CredentialReference.workspace_id == identity.workspace_id,
    ).order_by(CredentialReference.reference_name, desc(CredentialReference.version))).all()
    return {"credentials": [_credential_view(row) for row in rows]}


@router.get("/procedures")
def procedures(db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        _require(db, identity, "procedure.review", "procedure")
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    rows = db.scalars(select(ProcedureDefinition).order_by(
        ProcedureDefinition.procedure_code, desc(ProcedureDefinition.version)
    )).all()
    return {"procedures": [_procedure_view(row) for row in rows]}


def _procedure_action(db: Session, identity: IdentityContext, procedure_id: str, action: str) -> dict:
    permission = {
        "submit": "procedure.review", "approve": "procedure.review",
        "activate": "procedure.activate", "disable": "procedure.disable",
        "rollback": "procedure.rollback",
    }[action]
    _require(db, identity, permission, "procedure", resource_id=procedure_id)
    registry = ProcedureRegistry(db, identity)
    try:
        if action == "submit":
            row = registry.submit_review(procedure_id)
        elif action == "approve":
            row = registry.approve(procedure_id)
        elif action == "activate":
            row = registry.activate(procedure_id, rollout_status=ProcedureStatus.ACTIVE)
        elif action == "disable":
            row = registry.deprecate(procedure_id)
        else:
            row = registry.rollback(procedure_id)
    except ProcedureRegistryError as exc:
        if action == "activate":
            record_governance_event(
                db, identity,
                action="procedure.activate_denied",
                resource_type="procedure",
                resource_id=procedure_id,
                result="DENIED",
                detail={"code": exc.code},
                commit=True,
            )
        raise
    record_governance_event(
        db, identity,
        action=f"procedure.{action}",
        resource_type="procedure",
        resource_id=procedure_id,
        result="SUCCESS",
        commit=True,
    )
    return _procedure_view(row)


@router.post("/procedures/{procedure_id}/submit-review")
def submit_procedure(procedure_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _procedure_action(db, identity, procedure_id, "submit")
    except (ProcedureRegistryError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/procedures/{procedure_id}/approve")
def approve_procedure(procedure_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _procedure_action(db, identity, procedure_id, "approve")
    except (ProcedureRegistryError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/procedures/{procedure_id}/activate")
def activate_procedure(procedure_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _procedure_action(db, identity, procedure_id, "activate")
    except (ProcedureRegistryError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/procedures/{procedure_id}/disable")
def disable_procedure(procedure_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _procedure_action(db, identity, procedure_id, "disable")
    except (ProcedureRegistryError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/procedures/{procedure_id}/rollback")
def rollback_procedure(procedure_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _procedure_action(db, identity, procedure_id, "rollback")
    except (ProcedureRegistryError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/credentials")
def create_credential(payload: CredentialRequest, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _credential_view(CredentialReferenceService(db, identity).create(**payload.model_dump()))
    except (SecretResolutionError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/credentials/{credential_ref_id}/rotate")
def rotate_credential(credential_ref_id: str, payload: CredentialRotateRequest, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _credential_view(CredentialReferenceService(db, identity).rotate(credential_ref_id, **payload.model_dump()))
    except (SecretResolutionError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/credentials/{credential_ref_id}/disable")
def disable_credential(credential_ref_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _credential_view(CredentialReferenceService(db, identity).set_status(credential_ref_id, CredentialStatus.DISABLED))
    except (SecretResolutionError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/credentials/{credential_ref_id}/revoke")
def revoke_credential(credential_ref_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _credential_view(CredentialReferenceService(db, identity).set_status(credential_ref_id, CredentialStatus.REVOKED))
    except (SecretResolutionError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.get("/credential-usage")
def credential_usage(db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        _require(db, identity, "audit.view", "audit")
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    rows = db.scalars(select(CredentialUsageAudit).where(
        CredentialUsageAudit.tenant_id == identity.tenant_id,
        CredentialUsageAudit.workspace_id == identity.workspace_id,
    ).order_by(desc(CredentialUsageAudit.created_at)).limit(200)).all()
    return {"usage": [{
        "usage_id": row.usage_id, "credential_ref_id": row.credential_ref_id,
        "actor": row.actor_subject_id, "action": row.action, "outcome": row.outcome,
        "error_code": row.error_code, "trace_id": row.trace_id, "created_at": row.created_at,
        "secret_value_exposed": False,
    } for row in rows]}


@router.post("/legal-holds")
def create_hold(payload: LegalHoldRequest, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        row = LegalHoldService(db, identity).create(**payload.model_dump())
        return {"legal_hold_id": row.legal_hold_id, "status": row.status}
    except (RetentionError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/legal-holds/{legal_hold_id}/release")
def release_hold(legal_hold_id: str, payload: ReasonRequest, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        row = LegalHoldService(db, identity).release(legal_hold_id, reason=payload.reason)
        return {"legal_hold_id": row.legal_hold_id, "status": row.status}
    except (RetentionError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/retention-policies")
def create_retention(payload: RetentionRequest, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        row = RetentionPolicyService(db, identity).create(**payload.model_dump())
        return {"retention_policy_id": row.retention_policy_id, "status": row.status, "version": row.version}
    except (RetentionError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/retention-policies/{retention_policy_id}/activate")
def activate_retention(retention_policy_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        row = RetentionPolicyService(db, identity).approve_and_activate(retention_policy_id)
        return {"retention_policy_id": row.retention_policy_id, "status": row.status}
    except (RetentionError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.get("/audit")
def audit_events(
    actor: str | None = None,
    resource: str | None = None,
    action: str | None = None,
    result: str | None = None,
    trace_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    identity: IdentityContext = Depends(trusted_identity),
) -> dict:
    try:
        _require(db, identity, "audit.view", "audit")
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    rows, total = GovernanceAuditQuery(db, identity).search(
        actor=actor, resource=resource, action=action, result=result, trace_id=trace_id,
        start=start, end=end, page=page, page_size=page_size,
    )
    return {"page": page, "page_size": page_size, "total": total, "events": [{
        "event_id": row.event_id, "tenant_id": row.tenant_id, "actor": row.actor_subject_id,
        "resource_type": row.resource_type, "resource_id": row.resource_id, "action": row.action,
        "result": row.result, "trace_id": row.trace_id, "created_at": row.created_at,
    } for row in rows]}


@router.get("/audit/export")
def export_audit(
    actor: str | None = None,
    resource: str | None = None,
    action: str | None = None,
    result: str | None = None,
    trace_id: str | None = None,
    db: Session = Depends(get_db),
    identity: IdentityContext = Depends(trusted_identity),
) -> PlainTextResponse:
    try:
        _require(db, identity, "audit.export", "audit")
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    content = GovernanceAuditQuery(db, identity).export_csv(
        actor=actor, resource=resource, action=action, result=result, trace_id=trace_id,
    )
    return PlainTextResponse(content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=governance-audit.csv"})


@router.get("/alerts")
def alerts(db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        _require(db, identity, "alert.view", "security_alert")
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    rows = db.scalars(select(SecurityAlert).where(
        SecurityAlert.tenant_id == identity.tenant_id,
        SecurityAlert.workspace_id == identity.workspace_id,
    ).order_by(desc(SecurityAlert.last_seen_at))).all()
    return {"alerts": [{
        "alert_id": row.alert_id, "rule_code": row.rule_code, "severity": row.severity,
        "status": row.status, "event_count": row.event_count, "summary": row.summary,
        "trace_id": row.trace_id, "last_seen_at": row.last_seen_at,
    } for row in rows]}


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        _require(db, identity, "alert.manage", "security_alert", resource_id=alert_id)
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    row = db.get(SecurityAlert, alert_id)
    if row is None or row.tenant_id != identity.tenant_id or row.workspace_id != identity.workspace_id:
        raise HTTPException(404, detail={"code": "ALERT_NOT_FOUND", "message": "安全告警不存在"})
    row.status = "ACKNOWLEDGED"
    row.acknowledged_by = identity.subject_id
    row.acknowledged_at = datetime.now().astimezone()
    record_governance_event(db, identity, action="alert.acknowledged", resource_type="security_alert", resource_id=alert_id, result="SUCCESS")
    db.commit()
    return {"alert_id": row.alert_id, "status": row.status}


@router.get("/releases")
def releases(db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        _require(db, identity, "release.review", "release")
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    rows = db.scalars(select(PlatformRelease).where(
        PlatformRelease.tenant_id == identity.tenant_id,
        PlatformRelease.workspace_id == identity.workspace_id,
    ).order_by(desc(PlatformRelease.created_at))).all()
    return {"releases": [_release_view(row) for row in rows], "production_release_enabled": False}


@router.post("/releases")
def create_release(payload: ReleaseRequest, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _release_view(ReleaseRegistry(db, identity).create(**payload.model_dump()))
    except (ReleaseGovernanceError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/releases/{release_id}/submit-review")
def submit_release(release_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _release_view(ReleaseRegistry(db, identity).submit_review(release_id))
    except (ReleaseGovernanceError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/releases/{release_id}/approve")
def approve_release(release_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _release_view(ReleaseRegistry(db, identity).approve(release_id))
    except (ReleaseGovernanceError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/releases/{release_id}/activate")
def activate_release(release_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _release_view(ReleaseRegistry(db, identity).activate(release_id))
    except (ReleaseGovernanceError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.post("/releases/{release_id}/rollback")
def rollback_release(release_id: str, payload: RollbackRequest, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        return _release_view(ReleaseRegistry(db, identity).rollback(release_id, target_release_id=payload.target_release_id))
    except (ReleaseGovernanceError, AuthorizationDenied) as exc:
        raise _http_error(exc) from exc


@router.get("/runtime-health")
def runtime_health(db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    try:
        _require(db, identity, "health.view", "runtime_health")
    except AuthorizationDenied as exc:
        raise _http_error(exc) from exc
    readiness, status_code = readiness_snapshot()
    table_count = int(db.scalar(select(func.count()).select_from(Principal)) or 0)
    return {
        "readiness": readiness,
        "readiness_http_status": status_code,
        "principal_count": table_count,
        "query_engine_mode": get_settings().effective_query_engine_mode,
        "sqlbot_engine_enabled": get_settings().sqlbot_engine_enabled,
        "sqlbot_canary_eligible": False,
        "production_release_enabled": False,
        "capacity_evidence": "isolated_test_only",
        "data_classification": "simulated",
    }
