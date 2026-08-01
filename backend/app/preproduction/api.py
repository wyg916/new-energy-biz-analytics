from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.dependencies import trusted_identity
from app.core.config import get_settings
from app.core.database import get_db
from app.governance.authorization import AuthorizationDenied
from app.governance.models import CredentialReference, GovernanceAuditEvent, PlatformRelease
from app.governance.secrets import SecretProviderRegistry
from app.platform.identity import IdentityContext
from app.preproduction.alerts import ExternalAlertError, SignedWebhookAlertAdapter
from app.preproduction.datasource import DataSourceGovernanceError, DataSourceGovernanceService
from app.preproduction.models import ExternalAlertDelivery, PreproductionAcceptanceRecord
from app.preproduction.oidc import OIDCFlowService


router = APIRouter(prefix="/preproduction", tags=["preproduction"])


class DataSourceCreateRequest(BaseModel):
    display_name: str = Field(min_length=3, max_length=128)
    source_type: Literal["postgresql"] = "postgresql"
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    credential_ref_id: str = Field(min_length=8, max_length=64)
    scenario_id: Literal["charging_ops", "sales_ops"]


class DataSourceProfileRequest(BaseModel):
    relation: str = Field(min_length=3, max_length=255)


class DataSourceRotateRequest(BaseModel):
    secret_identifier: str = Field(min_length=5, max_length=160)


class DataSourceRollbackRequest(BaseModel):
    target_source_id: str = Field(min_length=8, max_length=64)


class AlertDeliveryRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


def _error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "PREPRODUCTION_REQUEST_REJECTED")
    if code.endswith("NOT_FOUND"):
        status_code = 404
    elif code in {"CROSS_TENANT_DENIED", "CROSS_WORKSPACE_DENIED", "RBAC_PERMISSION_DENIED", "ABAC_POLICY_NOT_MATCHED"}:
        status_code = 403
    elif code.endswith("UNAVAILABLE") or code == "EXTERNAL_ALERT_CIRCUIT_OPEN":
        status_code = 503
    elif "INVALID_STATE" in code or "MISMATCH" in code:
        status_code = 409
    else:
        status_code = 422
    return HTTPException(status_code=status_code, detail={"code": code, "message": str(exc)})


def _run(action):
    try:
        return action()
    except (DataSourceGovernanceError, ExternalAlertError, AuthorizationDenied) as exc:
        raise _error(exc) from exc


@router.get("/snapshot")
def snapshot(
    db: Session = Depends(get_db),
    identity: IdentityContext = Depends(trusted_identity),
) -> dict:
    settings = get_settings()
    data_sources = _run(lambda: DataSourceGovernanceService(db, identity).list())
    credentials = list(db.scalars(select(CredentialReference).where(
        CredentialReference.tenant_id == identity.tenant_id,
        CredentialReference.workspace_id == identity.workspace_id,
    ).order_by(CredentialReference.reference_name, desc(CredentialReference.version))).all())
    provider_health = {}
    for code, provider in SecretProviderRegistry().providers.items():
        health = getattr(provider, "health", None)
        provider_health[code] = {
            "configured": True,
            "status": "READY" if (health() if health else code == "ENV") else "UNAVAILABLE",
        }
    acceptance = list(db.scalars(select(PreproductionAcceptanceRecord).order_by(
        PreproductionAcceptanceRecord.category,
        desc(PreproductionAcceptanceRecord.finished_at),
    )).all())
    latest_by_category = {}
    for item in acceptance:
        latest_by_category.setdefault(item.category, item)
    acceptance_status = {
        category: item.status for category, item in latest_by_category.items()
    }
    rc = db.scalar(select(PlatformRelease).where(
        PlatformRelease.tenant_id == identity.tenant_id,
        PlatformRelease.workspace_id == identity.workspace_id,
        PlatformRelease.object_type == "RELEASE_CANDIDATE",
    ).order_by(desc(PlatformRelease.created_at)))
    delivery_counts = dict(db.execute(select(
        ExternalAlertDelivery.status, func.count(ExternalAlertDelivery.delivery_id),
    ).group_by(ExternalAlertDelivery.status)).all())
    sqlbot_gate_record = latest_by_category.get("SQLBOT_EXTERNAL")
    sqlbot_gate = {
        "status": sqlbot_gate_record.status if sqlbot_gate_record else "CONDITIONAL",
        "actual_external_requests": 0,
        "reason": "未提供经授权的外部模型 CredentialReference，已在网络请求前退出",
        "query_engine_mode": settings.effective_query_engine_mode,
        "engine_enabled": settings.sqlbot_engine_enabled,
        "canary_eligible": False,
    }
    required_pass_categories = {
        "OIDC_INTEGRATION", "SECRET_PROVIDER", "DATASOURCE_GOVERNANCE",
        "CAPACITY_SOAK", "FAILURE_RECOVERY", "BACKUP_RESTORE",
        "SECURITY_NEGATIVE", "FRONTEND_E2E", "FULL_REGRESSION",
    }
    code_complete = all(
        acceptance_status.get(category) == "PASS"
        for category in {"FRONTEND_E2E", "FULL_REGRESSION"}
    )
    acceptance_complete = (
        all(acceptance_status.get(category) == "PASS" for category in required_pass_categories)
        and acceptance_status.get("SQLBOT_EXTERNAL") == "CONDITIONAL"
    )
    gates = {
        "preproduction_code_complete": code_complete,
        "preproduction_acceptance_complete": acceptance_complete,
        "release_candidate_approved": bool(rc and rc.status in {"APPROVED", "ACTIVE"}),
        "enterprise_idp_approved": False,
        "external_model_approved": False,
        "production_change_window_approved": False,
        "production_release_authorized": settings.production_release_authorized,
    }
    return {
        "environment": "preproduction",
        "data": {
            "classification": "simulated",
            "period": {"start": "2025-01-01", "end_inclusive": "2026-06-30"},
            "source": "fixed-seed business-rule simulation stored in PostgreSQL",
            "run_id_location": "global runtime status and acceptance evidence",
        },
        "runtime": {
            "release_version": settings.release_version,
            "migration_head": settings.expected_database_revision,
            "query_engine_mode": settings.effective_query_engine_mode,
            "local_auth_enabled": settings.local_auth_enabled,
            "production_release_authorized": settings.production_release_authorized,
        },
        "oidc": OIDCFlowService(db).provider_health(),
        "secret_providers": provider_health,
        "credential_references": [
            {
                "credential_ref_id": row.credential_ref_id, "reference_name": row.reference_name,
                "provider": row.provider, "purpose": row.purpose, "version": row.version,
                "status": row.status, "value_returned": False,
            }
            for row in credentials
        ],
        "data_sources": data_sources,
        "external_alert": {**SignedWebhookAlertAdapter(db, identity).health(), "deliveries": delivery_counts},
        "sqlbot_external_evaluation": sqlbot_gate,
        "acceptance": [
            {
                "run_id": row.run_id, "category": row.category, "status": row.status,
                "evidence_hash": row.evidence_hash, "finished_at": row.finished_at.isoformat(),
                "metrics": json.loads(row.metrics_json or "{}"),
            }
            for row in latest_by_category.values()
        ],
        "release_candidate": None if rc is None else {
            "release_id": rc.release_id, "version": rc.version, "status": rc.status,
            "artifact_hash": rc.artifact_hash, "environment": rc.environment,
        },
        "production_gates": gates,
        "production_actions_enabled": False,
        "generated_at": datetime.now(UTC).isoformat(),
        "audit_event_count": int(db.scalar(select(func.count(GovernanceAuditEvent.event_id))) or 0),
    }


@router.get("/datasources")
def list_datasources(db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> list[dict]:
    return _run(lambda: DataSourceGovernanceService(db, identity).list())


@router.post("/datasources")
def create_datasource(payload: DataSourceCreateRequest, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    service = DataSourceGovernanceService(db, identity)
    record = _run(lambda: service.create(**payload.model_dump()))
    return service.payload(record)


@router.post("/datasources/{source_id}/test")
def test_datasource(source_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    return _run(lambda: DataSourceGovernanceService(db, identity).test_connection(source_id))


@router.post("/datasources/{source_id}/discover")
def discover_datasource(source_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    return _run(lambda: DataSourceGovernanceService(db, identity).discover_schema(source_id))


@router.post("/datasources/{source_id}/profile")
def profile_datasource(payload: DataSourceProfileRequest, source_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    return _run(lambda: DataSourceGovernanceService(db, identity).profile(source_id, relation=payload.relation))


@router.post("/datasources/{source_id}/lifecycle/{action}")
def change_datasource_lifecycle(
    source_id: str,
    action: Literal["submit", "approve", "publish", "activate", "disable", "archive"],
    db: Session = Depends(get_db),
    identity: IdentityContext = Depends(trusted_identity),
) -> dict:
    service = DataSourceGovernanceService(db, identity)
    record = _run(lambda: getattr(service, action)(source_id))
    return service.payload(record)


@router.post("/datasources/{source_id}/rotate")
def rotate_datasource(payload: DataSourceRotateRequest, source_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    service = DataSourceGovernanceService(db, identity)
    record = _run(lambda: service.rotate(source_id, secret_identifier=payload.secret_identifier))
    return service.payload(record)


@router.post("/datasources/{source_id}/rollback")
def rollback_datasource(payload: DataSourceRollbackRequest, source_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    service = DataSourceGovernanceService(db, identity)
    record = _run(lambda: service.rollback(source_id, target_source_id=payload.target_source_id))
    return service.payload(record)


@router.post("/alerts/{alert_id}/deliver")
def deliver_alert(payload: AlertDeliveryRequest, alert_id: str, db: Session = Depends(get_db), identity: IdentityContext = Depends(trusted_identity)) -> dict:
    return _run(lambda: SignedWebhookAlertAdapter(db, identity).deliver(alert_id, idempotency_key=payload.idempotency_key))
