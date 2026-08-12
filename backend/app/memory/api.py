from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.core.database import get_db
from app.memory.audit import audit_memory_use
from app.memory.authorization import MemoryAuthorization, MemoryAuthorizationError
from app.memory.contracts import MemoryStatus, MemoryType
from app.memory.deletion import MemoryDeletionService
from app.memory.metrics import memory_lifecycle_metrics
from app.memory.models import (
    MemoryDeleteVerification,
    MemoryLifecycleOutbox,
    MemoryLifecycleTask,
    MemoryRecord,
    MemoryWriteCandidateRecord,
)
from app.memory.policy import MemoryPolicyService
from app.memory.semantic import SemanticMemoryError, SemanticMemoryService
from app.memory.working import WorkingMemoryService
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.core.config import get_settings
from app.governance.authorization import AuthorizationDenied, AuthorizationService, request_context
from app.governance.audit import record_governance_event


router = APIRouter(prefix="/memory", tags=["memory"])


def _require(db: Session, user: User, action: str, *, resource_id: str | None = None, owner: str | None = None, scenario_id: str | None = None) -> None:
    identity = IdentityContextFactory.from_user(user)
    try:
        AuthorizationService(db, identity).require(request_context(
            identity,
            action=action,
            resource_type="memory",
            resource_id=resource_id,
            owner_subject_id=owner,
            scenario_id=scenario_id,
            environment=get_settings().app_env,
        ))
    except AuthorizationDenied as exc:
        raise HTTPException(403, detail={"code": exc.code, "message": str(exc)}) from exc


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


def _require_lifecycle_admin(db: Session, user: User) -> None:
    if user.role != "analyst_admin":
        raise HTTPException(403, detail={"code": "MEMORY_LIFECYCLE_ADMIN_REQUIRED", "message": "仅系统管理员可查看生命周期运行状态"})
    _require(db, user, "memory.view")


def _digest(value: str | None) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def _runtime_redis_client():
    settings = get_settings()
    if not settings.memory_lifecycle_redis_enabled:
        return None
    return Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
        decode_responses=True,
    )


@router.get("/records")
def list_records(
    scenario_id: str = Query(pattern=r"^(charging_ops|sales_ops)$"),
    memory_type: MemoryType | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    identity = IdentityContextFactory.from_user(user)
    _require(db, user, "memory.view", owner=identity.subject_id, scenario_id=scenario_id)
    types = (memory_type,) if memory_type else (
        MemoryType.SEMANTIC,
        MemoryType.EPISODIC,
        MemoryType.PROCEDURAL,
        MemoryType.GOVERNANCE,
    )
    current = datetime.now(UTC)
    filters = (
        MemoryAuthorization.retrieval_filter(identity, scenario_id=scenario_id),
        MemoryRecord.memory_type.in_(types),
        MemoryRecord.status.in_((MemoryStatus.ACTIVE, MemoryStatus.REDUCED_RANK)),
        MemoryRecord.deleted_at.is_(None),
        MemoryRecord.valid_from <= current,
        or_(MemoryRecord.valid_to.is_(None), MemoryRecord.valid_to > current),
        or_(MemoryRecord.expires_at.is_(None), MemoryRecord.expires_at > current),
    )
    total = int(db.scalar(select(func.count()).select_from(MemoryRecord).where(*filters)) or 0)
    records = db.scalars(
        select(MemoryRecord).where(*filters).order_by(
            desc(MemoryRecord.updated_at),
            desc(MemoryRecord.created_at),
            desc(MemoryRecord.version),
            MemoryRecord.memory_id,
        ).limit(limit)
    ).all()
    serialized = [_serialize(record) for record in records]
    audit_memory_use(
        db,
        identity,
        action="memory.manage.list",
        outcome="success",
        detail={
            "scenario_id": scenario_id,
            "memory_types": [str(item) for item in types],
            "result_count": len(serialized),
            "total": total,
            "limit": limit,
            "truncated": total > len(serialized),
        },
        commit=True,
    )
    return {
        "records": serialized,
        "total": total,
        "limit": limit,
        "truncated": total > len(serialized),
        "memory_enabled": MemoryPolicyService(db, identity).is_enabled(
            scenario_id=scenario_id
        ),
        "data_classification": get_settings().runtime_data_classification,
    }


@router.get("/working/{session_id}")
def working_memory(
    session_id: str,
    scenario_id: str = Query(pattern=r"^(charging_ops|sales_ops)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    _require(db, user, "memory.view", resource_id=session_id, owner=f"user:{user.id}", scenario_id=scenario_id)
    result = WorkingMemoryService.from_runtime(
        db, IdentityContextFactory.from_user(user)
    ).load(scenario_id=scenario_id, session_id=session_id)
    return result.model_dump(mode="json")


@router.get("/candidates")
def candidates(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    _require(db, user, "memory.view", owner=f"user:{user.id}")
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
    _require(db, user, "memory.correct", owner=f"user:{user.id}", scenario_id=payload.scenario_id)
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
        record_governance_event(
            db,
            IdentityContextFactory.from_user(user),
            action="memory.write_candidate",
            resource_type="memory",
            resource_id=candidate.candidate_id,
            result="SUCCESS",
            detail={"memory_type": candidate.memory_type, "scenario_id": candidate.scenario_id},
            commit=True,
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
    _require(db, user, "memory.confirm", resource_id=candidate_id, owner=f"user:{user.id}")
    try:
        record = SemanticMemoryService(
            db, IdentityContextFactory.from_user(user)
        ).confirm(candidate_id)
        record_governance_event(
            db,
            IdentityContextFactory.from_user(user),
            action="memory.confirm",
            resource_type="memory",
            resource_id=record.memory_id,
            result="SUCCESS",
            commit=True,
        )
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
    _require(db, user, "memory.correct", resource_id=candidate_id, owner=f"user:{user.id}")
    try:
        SemanticMemoryService(
            db, IdentityContextFactory.from_user(user)
        ).reject(candidate_id, reason=payload.reason)
        record_governance_event(
            db,
            IdentityContextFactory.from_user(user),
            action="memory.correct",
            resource_type="memory",
            resource_id=candidate_id,
            result="REJECTED",
            commit=True,
        )
        return {"status": "REJECTED", "candidate_id": candidate_id}
    except SemanticMemoryError as exc:
        raise HTTPException(404, detail={"code": exc.code, "message": exc.message}) from exc


@router.put("/settings")
def set_memory_enabled(
    payload: MemorySettingRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    _require(db, user, "memory.correct", owner=f"user:{user.id}")
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
    record = db.get(MemoryRecord, memory_id)
    _require(
        db, user, "memory.delete", resource_id=memory_id,
        owner=record.user_id if record else f"user:{user.id}",
        scenario_id=record.scenario_id if record else None,
    )
    try:
        redis_client = _runtime_redis_client()
        try:
            result = MemoryDeletionService(
                db, IdentityContextFactory.from_user(user), redis_client=redis_client
            ).delete_one(memory_id, reason=reason)
        finally:
            if redis_client is not None:
                redis_client.close()
        record_governance_event(
            db,
            IdentityContextFactory.from_user(user),
            action="memory.delete",
            resource_type="memory",
            resource_id=memory_id,
            result=("SUCCESS" if result.verification_passed else "PENDING") if result.deleted_count else "BLOCKED",
            detail=result.__dict__,
            commit=True,
        )
        return result.__dict__
    except MemoryAuthorizationError as exc:
        raise HTTPException(403, detail={"code": exc.code, "message": exc.message}) from exc


@router.delete("/current-user")
def delete_current_user_memory(
    reason: str = Query(min_length=2, max_length=500),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    _require(db, user, "memory.delete", owner=f"user:{user.id}")
    redis_client = _runtime_redis_client()
    try:
        result = MemoryDeletionService(
            db, IdentityContextFactory.from_user(user), redis_client=redis_client
        ).purge_current_user(reason=reason)
    finally:
        if redis_client is not None:
            redis_client.close()
    record_governance_event(
        db,
        IdentityContextFactory.from_user(user),
        action="memory.delete_user",
        resource_type="memory",
        resource_id=f"user:{user.id}",
        result=("SUCCESS" if result.verification_passed else "PENDING") if result.deleted_count else "NOOP",
        detail=result.__dict__,
        commit=True,
    )
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


@router.get("/lifecycle/tasks")
def lifecycle_tasks(
    status: str | None = Query(default=None, max_length=24),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    _require_lifecycle_admin(db, user)
    identity = IdentityContextFactory.from_user(user)
    filters = [
        MemoryLifecycleTask.tenant_id == identity.tenant_id,
        MemoryLifecycleTask.organization_id == identity.org_id,
        MemoryLifecycleTask.workspace_id == identity.workspace_id,
    ]
    if status:
        filters.append(MemoryLifecycleTask.status == status.upper())
    rows = db.scalars(select(MemoryLifecycleTask).where(*filters).order_by(
        MemoryLifecycleTask.created_at.desc()
    ).limit(limit)).all()
    return {"tasks": [{
        "task_id": row.task_id,
        "task_type": row.task_type,
        "status": row.status,
        "scenario_id": row.scenario_id,
        "memory_id_hash": _digest(row.memory_id),
        "user_id_hash": _digest(row.user_id),
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
        "next_attempt_at": row.next_attempt_at,
        "failure_reason": row.failure_reason,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "finished_at": row.finished_at,
    } for row in rows]}


@router.get("/lifecycle/tasks/{task_id}/delete-verification")
def lifecycle_delete_verification(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    _require_lifecycle_admin(db, user)
    identity = IdentityContextFactory.from_user(user)
    task = db.scalar(select(MemoryLifecycleTask).where(
        MemoryLifecycleTask.task_id == task_id,
        MemoryLifecycleTask.tenant_id == identity.tenant_id,
        MemoryLifecycleTask.organization_id == identity.org_id,
        MemoryLifecycleTask.workspace_id == identity.workspace_id,
    ))
    if task is None:
        raise HTTPException(404, detail={"code": "LIFECYCLE_TASK_NOT_FOUND", "message": "生命周期任务不存在"})
    rows = db.scalars(select(MemoryDeleteVerification).where(
        MemoryDeleteVerification.task_id == task_id
    ).order_by(MemoryDeleteVerification.target_store)).all()
    return {
        "task_id": task_id,
        "task_status": task.status,
        "delete_no_recall": all(row.status in {"VERIFIED", "NOT_CONFIGURED"} for row in rows) and bool(rows),
        "stores": [{
            "target_store": row.target_store,
            "status": row.status,
            "resource_id_hash": row.resource_id_hash,
            "checked_at": row.checked_at,
        } for row in rows],
    }


@router.get("/lifecycle/metrics")
def lifecycle_metrics(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    _require_lifecycle_admin(db, user)
    identity = IdentityContextFactory.from_user(user)
    task_rows = db.execute(select(
        MemoryLifecycleTask.status, func.count()
    ).where(
        MemoryLifecycleTask.tenant_id == identity.tenant_id,
        MemoryLifecycleTask.organization_id == identity.org_id,
        MemoryLifecycleTask.workspace_id == identity.workspace_id,
    ).group_by(MemoryLifecycleTask.status)).all()
    outbox_rows = db.execute(select(
        MemoryLifecycleOutbox.status, func.count()
    ).join(MemoryLifecycleTask, MemoryLifecycleTask.task_id == MemoryLifecycleOutbox.task_id).where(
        MemoryLifecycleTask.tenant_id == identity.tenant_id,
        MemoryLifecycleTask.organization_id == identity.org_id,
        MemoryLifecycleTask.workspace_id == identity.workspace_id,
    ).group_by(MemoryLifecycleOutbox.status)).all()
    return {
        "tasks_by_status": {status: count for status, count in task_rows},
        "outbox_by_status": {status: count for status, count in outbox_rows},
        "process_metrics": memory_lifecycle_metrics.snapshot(),
        "data_classification": "operational_metadata",
        "content_included": False,
    }
