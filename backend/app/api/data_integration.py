import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import Session

from app.api.dashboard import validate_range
from app.api.dependencies import current_user, require_roles
from app.core.database import get_db
from app.models.auth import AuditLog, User
from app.services.data_integration import DataIntegrationError, DataIntegrationService

router = APIRouter(prefix="/data-integration", tags=["data-integration"])


class ConnectionTestRequest(BaseModel):
    password: SecretStr | None = None
    resource_locator: str | None = Field(default=None, max_length=512)


class IngestionRequest(BaseModel):
    start: date
    end_exclusive: date
    password: SecretStr | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class ReviewDecisionRequest(BaseModel):
    action: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)


def _http_error(exc: DataIntegrationError) -> HTTPException:
    if exc.code == "FORBIDDEN":
        status_code = 403
    elif exc.code.endswith("NOT_FOUND"):
        status_code = 404
    elif exc.code in {"WORKFLOW_INVALID_STATE", "STALE_INGESTION_RUN"}:
        status_code = 409
    else:
        status_code = 422
    return HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})


def _audit(db: Session, user: User, action: str, resource: str, outcome: str, detail: dict) -> None:
    db.add(AuditLog(
        actor_user_id=user.id,
        action=action,
        resource=resource,
        outcome=outcome,
        detail_json=json.dumps(detail, ensure_ascii=False),
    ))
    db.commit()


@router.get("/overview")
def overview(
    start: date,
    end_exclusive: date,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    validate_range(start, end_exclusive)
    try:
        return DataIntegrationService(db, user).overview(start, end_exclusive)
    except DataIntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/sources/{source_id}/test")
def test_source(
    source_id: str,
    payload: ConnectionTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        result = DataIntegrationService(db, user).test_source(
            source_id,
            payload.password.get_secret_value() if payload.password else None,
            payload.resource_locator,
        )
        _audit(db, user, "data_source.test", source_id, "passed", {
            "source_type": result["source_type"],
            "latency_ms": result["latency_ms"],
            "credential_persisted": False,
        })
        return result
    except DataIntegrationError as exc:
        db.rollback()
        _audit(db, user, "data_source.test", source_id, "failed", {"error_code": exc.code, "credential_persisted": False})
        raise _http_error(exc) from exc


@router.post("/datasets/{dataset_id}/run")
def run_ingestion(
    dataset_id: str,
    payload: IngestionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    validate_range(payload.start, payload.end_exclusive)
    try:
        result = DataIntegrationService(db, user).ingest_dataset(
            dataset_id,
            payload.start,
            payload.end_exclusive,
            payload.password.get_secret_value() if payload.password else None,
            payload.limit,
        )
        _audit(db, user, "data_ingestion.run", dataset_id, "completed", {
            "run_id": result["run_id"],
            "rows_read": result["rows_read"],
            "rows_written": result["rows_written"],
        })
        return result
    except DataIntegrationError as exc:
        db.rollback()
        _audit(db, user, "data_ingestion.run", dataset_id, "failed", {"error_code": exc.code})
        raise _http_error(exc) from exc


@router.post("/datasets/{dataset_id}/runs/{run_id}/quality")
def validate_ingestion(
    dataset_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        result = DataIntegrationService(db, user).validate_ingestion(dataset_id, run_id)
        _audit(db, user, "data_ingestion.quality", run_id, result["quality_status"], {
            "dataset_id": dataset_id,
            "rules_checked": result["summary"]["rules_checked"],
            "failures": result["summary"]["failures"],
        })
        return result
    except DataIntegrationError as exc:
        db.rollback()
        _audit(db, user, "data_ingestion.quality", run_id, "failed", {"dataset_id": dataset_id, "error_code": exc.code})
        raise _http_error(exc) from exc


@router.post("/datasets/{dataset_id}/runs/{run_id}/submit")
def submit_ingestion(
    dataset_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        result = DataIntegrationService(db, user).submit_ingestion(dataset_id, run_id)
        _audit(db, user, "data_ingestion.submit", run_id, "pending_approval", {"dataset_id": dataset_id})
        return result
    except DataIntegrationError as exc:
        db.rollback()
        _audit(db, user, "data_ingestion.submit", run_id, "failed", {"dataset_id": dataset_id, "error_code": exc.code})
        raise _http_error(exc) from exc


@router.post("/datasets/{dataset_id}/runs/{run_id}/review")
def review_ingestion(
    dataset_id: str,
    run_id: str,
    payload: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        result = DataIntegrationService(db, user).decide_ingestion(
            dataset_id, run_id, payload.action, payload.reason,
        )
        _audit(db, user, "data_ingestion.review", run_id, result["workflow_status"], {
            "dataset_id": dataset_id,
            "action": payload.action,
            "reason_supplied": bool(payload.reason),
        })
        return result
    except DataIntegrationError as exc:
        db.rollback()
        _audit(db, user, "data_ingestion.review", run_id, "failed", {"dataset_id": dataset_id, "error_code": exc.code})
        raise _http_error(exc) from exc


@router.post("/datasets/{dataset_id}/runs/{run_id}/publish")
def publish_ingestion(
    dataset_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        result = DataIntegrationService(db, user).publish_ingestion(dataset_id, run_id)
        _audit(db, user, "data_ingestion.publish", run_id, "published", {
            "dataset_id": dataset_id,
            "release_version": result["release_version"],
        })
        return result
    except DataIntegrationError as exc:
        db.rollback()
        _audit(db, user, "data_ingestion.publish", run_id, "failed", {"dataset_id": dataset_id, "error_code": exc.code})
        raise _http_error(exc) from exc
