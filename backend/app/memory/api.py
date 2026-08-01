from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.core.database import get_db
from app.memory.authorization import MemoryAuthorizationError
from app.memory.contracts import MemoryType
from app.memory.deletion import MemoryDeletionService
from app.memory.models import MemoryRecord, MemoryWriteCandidateRecord
from app.memory.policy import MemoryPolicyService
from app.memory.retrieval import MemoryRetriever
from app.memory.semantic import SemanticMemoryError, SemanticMemoryService
from app.memory.working import WorkingMemoryService
from app.models.auth import User
from app.platform.identity import IdentityContextFactory


router = APIRouter(prefix="/memory", tags=["memory"])


class SemanticPreferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=2, max_length=64)
    value: Any
    scenario_id: str | None = Field(default=None, pattern=r"^(charging_ops|sales_ops)$")
    confirmed: bool = False
    write_reason: str = Field(min_length=2, max_length=256)


class CandidateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=2, max_length=500)


class MemorySettingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


def _serialize(record: MemoryRecord) -> dict:
    return {
        "memory_id": record.memory_id,
        "memory_type": record.memory_type,
        "scope_type": record.scope_type,
        "scenario_id": record.scenario_id,
        "content": record.content,
        "structured_value": json.loads(record.structured_value_json),
        "source_type": record.source_type,
        "source_id": record.source_id,
        "trust_level": record.trust_level,
        "confidence": record.confidence,
        "importance": record.importance,
        "status": record.status,
        "version": record.version,
        "expires_at": record.expires_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


@router.get("/records")
def list_records(
    scenario_id: str = Query(pattern=r"^(charging_ops|sales_ops)$"),
    memory_type: MemoryType | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    identity = IdentityContextFactory.from_user(user)
    types = (memory_type,) if memory_type else (
        MemoryType.SEMANTIC,
        MemoryType.EPISODIC,
        MemoryType.PROCEDURAL,
        MemoryType.GOVERNANCE,
    )
    result = MemoryRetriever(db, identity).retrieve(
        scenario_id=scenario_id,
        memory_types=types,
        limit=50,
        token_budget=20000,
    )
    return {
        "records": [_serialize(record) for record in result.records],
        "memory_enabled": MemoryPolicyService(db, identity).is_enabled(
            scenario_id=scenario_id
        ),
        "data_classification": "simulated",
    }


@router.get("/working/{session_id}")
def working_memory(
    session_id: str,
    scenario_id: str = Query(pattern=r"^(charging_ops|sales_ops)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    result = WorkingMemoryService.from_runtime(
        db, IdentityContextFactory.from_user(user)
    ).load(scenario_id=scenario_id, session_id=session_id)
    return result.model_dump(mode="json")


@router.get("/candidates")
def candidates(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    identity = IdentityContextFactory.from_user(user)
    rows = db.scalars(select(MemoryWriteCandidateRecord).where(
        MemoryWriteCandidateRecord.tenant_id == identity.tenant_id,
        MemoryWriteCandidateRecord.organization_id == identity.org_id,
        MemoryWriteCandidateRecord.workspace_id == identity.workspace_id,
        MemoryWriteCandidateRecord.user_id == identity.subject_id,
    ).order_by(MemoryWriteCandidateRecord.created_at.desc())).all()
    return {"candidates": [{
        "candidate_id": row.candidate_id,
        "memory_type": row.memory_type,
        "scenario_id": row.scenario_id,
        "content": row.content,
        "source_type": row.source_type,
        "trust_level": row.trust_level,
        "confidence": row.confidence,
        "status": row.status,
        "write_reason": row.write_reason,
        "rejection_reason": row.rejection_reason,
        "created_at": row.created_at,
    } for row in rows]}


@router.post("/preferences")
def propose_preference(
    payload: SemanticPreferenceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        candidate = SemanticMemoryService(
            db, IdentityContextFactory.from_user(user)
        ).propose(
            key=payload.key,
            value=payload.value,
            scenario_id=payload.scenario_id,
            source_type="USER_STATEMENT",
            source_id=None,
            explicitly_confirmed=payload.confirmed,
            idempotency_key=f"api:{user.id}:{uuid4()}",
            write_reason=payload.write_reason,
        )
        return {
            "candidate_id": candidate.candidate_id,
            "status": candidate.status,
            "approval_required": candidate.approval_required,
        }
    except SemanticMemoryError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/candidates/{candidate_id}/confirm")
def confirm_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        record = SemanticMemoryService(
            db, IdentityContextFactory.from_user(user)
        ).confirm(candidate_id)
        return _serialize(record)
    except SemanticMemoryError as exc:
        raise HTTPException(404, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/candidates/{candidate_id}/reject")
def reject_candidate(
    candidate_id: str,
    payload: CandidateDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        SemanticMemoryService(
            db, IdentityContextFactory.from_user(user)
        ).reject(candidate_id, reason=payload.reason)
        return {"status": "REJECTED", "candidate_id": candidate_id}
    except SemanticMemoryError as exc:
        raise HTTPException(404, detail={"code": exc.code, "message": exc.message}) from exc


@router.put("/settings")
def set_memory_enabled(
    payload: MemorySettingRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    service = SemanticMemoryService(db, IdentityContextFactory.from_user(user))
    candidate = service.propose(
        key="memory_enabled",
        value=payload.enabled,
        scenario_id=None,
        source_type="USER_SETTING",
        source_id=None,
        explicitly_confirmed=True,
        idempotency_key=f"memory-setting:{user.id}:{uuid4()}",
        write_reason="用户明确修改记忆开关",
    )
    record = service.confirm(candidate.candidate_id)
    return {"memory_enabled": payload.enabled, "memory_id": record.memory_id}


@router.delete("/records/{memory_id}")
def delete_record(
    memory_id: str,
    reason: str = Query(min_length=2, max_length=500),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        result = MemoryDeletionService(
            db, IdentityContextFactory.from_user(user)
        ).delete_one(memory_id, reason=reason)
        return result.__dict__
    except MemoryAuthorizationError as exc:
        raise HTTPException(403, detail={"code": exc.code, "message": exc.message}) from exc


@router.delete("/current-user")
def delete_current_user_memory(
    reason: str = Query(min_length=2, max_length=500),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    result = MemoryDeletionService(
        db, IdentityContextFactory.from_user(user)
    ).purge_current_user(reason=reason)
    return result.__dict__


@router.get("/export")
def export_memory(
    scenario_id: str = Query(pattern=r"^(charging_ops|sales_ops)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    response = list_records(scenario_id, None, db, user)
    return {
        "export_version": "p2b-1.0",
        "data_classification": "simulated",
        "source": "governed PostgreSQL memory_record",
        "run_id_location": "records[].structured_value.run_id when applicable",
        **response,
    }
