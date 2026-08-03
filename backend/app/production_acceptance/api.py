from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.dependencies import trusted_identity
from app.core.database import get_db
from app.governance.authorization import AuthorizationDenied
from app.platform.identity import IdentityContext
from app.production_acceptance.models import ProductionGate, ProductionGateHistory
from app.production_acceptance.registry import ProductionGateError, ProductionGateRegistry


router = APIRouter(prefix="/production-acceptance", tags=["production-acceptance"])


class GateEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: Literal["test_result", "security_scan", "manifest", "approval", "runbook", "runtime_probe"]
    uri: str = Field(min_length=4, max_length=500)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    observed_at: datetime
    summary: str = Field(min_length=3, max_length=500)

    @field_validator("uri")
    @classmethod
    def evidence_uri_must_be_a_reference(cls, value: str) -> str:
        allowed = ("docs/", "run://", "registry://", "approval://", "runtime://")
        if not value.startswith(allowed):
            raise ValueError("evidence URI must be a controlled reference")
        return value


class GateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["OPEN", "IN_PROGRESS", "PASSED", "WAIVED", "BLOCKED", "EXPIRED"]
    evidence: list[GateEvidenceRequest] = Field(default_factory=list, max_length=32)
    expires_at: datetime
    reason: str = Field(min_length=8, max_length=500)
    waiver_approved_by: str | None = Field(default=None, max_length=128)
    waiver_basis: str | None = Field(default=None, max_length=500)
    waiver_evidence_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AuthorizationDenied):
        return HTTPException(403, detail={"code": exc.code, "message": str(exc)})
    code = getattr(exc, "code", "PRODUCTION_GATE_REQUEST_REJECTED")
    status = 404 if code.endswith("NOT_FOUND") else 409
    return HTTPException(status, detail={"code": code, "message": str(exc)})


def _gate_view(registry: ProductionGateRegistry, gate: ProductionGate) -> dict:
    effective = registry.effective_status(gate)
    return {
        "gate_id": gate.gate_id,
        "gate_code": gate.gate_code,
        "title": gate.title,
        "category": gate.category,
        "environment": gate.environment,
        "status": effective,
        "recorded_status": gate.status,
        "display_status": "CONDITIONAL" if gate.external_condition and effective == "OPEN" else effective,
        "owner": gate.owner_role,
        "blocker_level": gate.blocker_level,
        "external_condition": gate.external_condition,
        **registry.release_scope(gate.gate_code),
        "evidence": json.loads(gate.evidence_json or "[]"),
        "evidence_hash": gate.evidence_hash,
        "expires_at": gate.expires_at,
        "last_verified_at": gate.last_verified_at,
        "review_requirement": gate.review_requirement,
        "waiver": None if gate.status != "WAIVED" else {
            "approved_by": gate.waiver_approved_by,
            "basis": gate.waiver_basis,
            "evidence_hash": gate.waiver_evidence_hash,
        },
        "version": gate.version,
        "updated_at": gate.updated_at,
    }


def _history_view(row: ProductionGateHistory) -> dict:
    return {
        "history_id": row.history_id,
        "gate_code": row.gate_code,
        "previous_status": row.previous_status,
        "status": row.status,
        "evidence": json.loads(row.evidence_json or "[]"),
        "evidence_hash": row.evidence_hash,
        "reason": row.reason,
        "actor_subject_id": row.actor_subject_id,
        "version": row.version,
        "created_at": row.created_at,
    }


@router.get("/snapshot")
def snapshot(
    db: Session = Depends(get_db),
    identity: IdentityContext = Depends(trusted_identity),
) -> dict:
    registry = ProductionGateRegistry(db, identity)
    try:
        gates = registry.list()
    except (AuthorizationDenied, ProductionGateError) as exc:
        raise _http_error(exc) from exc
    return {
        "environment": "production-acceptance",
        "data": {
            "classification": "simulated",
            "period": {"start": "2025-01-01", "end_inclusive": "2026-06-30"},
            "source": "fixed-seed business-rule simulation stored in the governed database",
            "run_id_location": "gate evidence and global runtime status",
        },
        "gates": [_gate_view(registry, gate) for gate in gates],
        "summary": registry.summary(gates),
        "runtime_contract": {
            "query_engine_mode": "SHADOW",
            "sqlbot_release_scope": "NOT_INCLUDED_IN_V4_RELEASE",
            "sqlbot_engine_enabled": False,
            "sqlbot_image_in_bom": False,
            "sqlbot_canary_eligible": False,
            "sqlbot_external_evaluation": "DEFERRED",
            "rag_runtime_mode": "KEYWORD_ONLY",
            "rag_vector_released": False,
            "production_release_authorized": False,
            "production_traffic_switched": False,
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/gates/{gate_code}/history")
def gate_history(
    gate_code: str,
    db: Session = Depends(get_db),
    identity: IdentityContext = Depends(trusted_identity),
) -> dict:
    try:
        rows = ProductionGateRegistry(db, identity).history(gate_code)
    except (AuthorizationDenied, ProductionGateError) as exc:
        raise _http_error(exc) from exc
    return {"gate_code": gate_code, "history": [_history_view(row) for row in rows]}


@router.post("/gates/{gate_code}/decision")
def decide_gate(
    gate_code: str,
    payload: GateDecisionRequest,
    db: Session = Depends(get_db),
    identity: IdentityContext = Depends(trusted_identity),
) -> dict:
    registry = ProductionGateRegistry(db, identity)
    try:
        gate = registry.decide(
            gate_code,
            status=payload.status,
            evidence=[item.model_dump(mode="json") for item in payload.evidence],
            expires_at=payload.expires_at,
            reason=payload.reason,
            waiver_approved_by=payload.waiver_approved_by,
            waiver_basis=payload.waiver_basis,
            waiver_evidence_hash=payload.waiver_evidence_hash,
        )
    except (AuthorizationDenied, ProductionGateError) as exc:
        raise _http_error(exc) from exc
    return _gate_view(registry, gate)
