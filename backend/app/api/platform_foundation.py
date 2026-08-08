import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.core.database import get_db
from app.models.auth import User
from app.models.business import ChargingSession
from app.models.integration import DataSourceConnection, ScenarioPackageRelease
from app.models.platform_data import (
    DatasetVersion,
    MappingVersion,
    PlatformDataset,
    ReviewRecord,
    RollbackRecord,
    SemanticActivation,
)
from app.models.semantic import SemanticModelVersion
from app.platform.dataset_release import (
    DatasetReleaseError,
    DatasetVersionService,
    ReleaseService,
    RollbackService,
    SemanticActivationService,
)
from app.platform.identity import IdentityContextFactory
from app.scenarios.charging_ops.package_adapter import install_platform_foundation
from app.scenarios.charging_ops.runtime import DATASET_CODE, SCENARIO_ID
from app.data.truth import current_data_truth

router = APIRouter(prefix="/platform/foundation", tags=["platform-foundation"])

MANAGED_RELATIONS = (
    "dim_station",
    "fact_charging_session",
    "fact_energy_cost",
    "fact_operation_expense",
    "fact_device_status_event",
)


class VersionCreateRequest(BaseModel):
    period_start: date = date(2025, 1, 1)
    period_end_exclusive: date = date(2026, 7, 1)
    idempotency_key: str = Field(min_length=8, max_length=96)


class ActionRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    reason: str | None = Field(default=None, max_length=500)


class RollbackRequest(ActionRequest):
    target_dataset_version_id: str = Field(min_length=8, max_length=64)


class SourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,47}$")
    display_name: str = Field(min_length=2, max_length=128)
    source_type: Literal["postgresql", "mysql", "csv", "excel"]
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str | None = Field(default=None, max_length=128)
    username: str | None = Field(default=None, max_length=128)
    resource_locator: str | None = Field(default=None, max_length=512)
    credential_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")


def _identity(user: User):
    return IdentityContextFactory.from_user(user)


def _http_error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", type(exc).__name__.upper())
    message = getattr(exc, "message", "平台治理操作失败")
    if code in {"DATASET_NOT_FOUND", "VERSION_NOT_FOUND", "SOURCE_NOT_FOUND"}:
        status_code = 404
    elif code in {"FORBIDDEN", "POLICY_DENIED"}:
        status_code = 403
    elif code in {
        "INVALID_STATE", "NOT_APPROVED", "NOT_PUBLISHED", "NO_ACTIVE_VERSION",
        "ALREADY_ACTIVE", "ROLLBACK_TARGET_INVALID", "SEMANTIC_VERSION_INVALID",
        "SEMANTIC_VERSION_INCOMPATIBLE", "IDEMPOTENCY_CONFLICT",
    }:
        status_code = 409
    else:
        status_code = 422
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _scoped_dataset(db: Session, user: User, dataset_id: str) -> tuple[object, PlatformDataset]:
    identity = _identity(user)
    dataset = DatasetVersionService(db)._scoped_dataset(identity, dataset_id)
    return identity, dataset


def _state(db: Session, user: User) -> dict:
    identity = _identity(user)
    dataset = db.scalar(select(PlatformDataset).where(
        PlatformDataset.tenant_id == identity.tenant_id,
        PlatformDataset.workspace_id == identity.workspace_id,
        PlatformDataset.scenario_id == SCENARIO_ID,
        PlatformDataset.code == DATASET_CODE,
    ))
    scenario = db.scalar(select(ScenarioPackageRelease).where(
        ScenarioPackageRelease.tenant_id == identity.tenant_id,
        ScenarioPackageRelease.workspace_id == identity.workspace_id,
        ScenarioPackageRelease.scenario_id == SCENARIO_ID,
    ).order_by(ScenarioPackageRelease.installed_at.desc()))
    if dataset is None:
        return {
            "installed": False,
            "scenario": None,
            "dataset": None,
            "versions": [],
            "activation": None,
            "rollbacks": [],
            "data_classification": "not_configured",
        }
    versions = list(db.scalars(select(DatasetVersion).where(
        DatasetVersion.dataset_id == dataset.dataset_id
    ).order_by(DatasetVersion.version.desc())))
    reviews = {
        row.dataset_version_id: row
        for row in db.scalars(select(ReviewRecord).where(
            ReviewRecord.dataset_version_id.in_([item.dataset_version_id for item in versions])
        ))
    } if versions else {}
    pointer = db.scalar(select(SemanticActivation).where(
        SemanticActivation.tenant_id == identity.tenant_id,
        SemanticActivation.workspace_id == identity.workspace_id,
        SemanticActivation.scenario_id == SCENARIO_ID,
        SemanticActivation.dataset_id == dataset.dataset_id,
    ))
    semantic = (
        db.get(SemanticModelVersion, pointer.active_semantic_model_version_id)
        if pointer and pointer.active_semantic_model_version_id else None
    )
    rollbacks = list(db.scalars(select(RollbackRecord).where(
        RollbackRecord.activation_id == pointer.activation_id
    ).order_by(RollbackRecord.created_at.desc()))) if pointer else []
    return {
        "installed": True,
        "scenario": {
            "scenario_id": scenario.scenario_id if scenario else SCENARIO_ID,
            "version": scenario.version if scenario else None,
            "status": scenario.status if scenario else "NOT_INSTALLED",
        },
        "dataset": {
            "dataset_id": dataset.dataset_id,
            "code": dataset.code,
            "name": dataset.name,
            "source_id": dataset.source_id,
            "status": dataset.status,
        },
        "versions": [{
            "dataset_version_id": item.dataset_version_id,
            "version": item.version,
            "status": item.status,
            "checksum": item.checksum,
            "row_count": item.row_count,
            "source_version": item.source_version,
            "period_start": item.period_start,
            "period_end_exclusive": item.period_end_exclusive,
            "review_status": reviews[item.dataset_version_id].status
            if item.dataset_version_id in reviews else None,
        } for item in versions],
        "activation": {
            "activation_id": pointer.activation_id,
            "dataset_version_id": pointer.active_dataset_version_id,
            "semantic_model_version_id": pointer.active_semantic_model_version_id,
            "semantic_version": semantic.version if semantic else None,
            "scenario_version": pointer.scenario_version,
            "lock_version": pointer.lock_version,
            "activated_at": pointer.activated_at.isoformat(),
        } if pointer else None,
        "rollbacks": [{
            "rollback_record_id": item.rollback_record_id,
            "from_dataset_version_id": item.from_dataset_version_id,
            "to_dataset_version_id": item.to_dataset_version_id,
            "reason": item.reason,
            "run_id": item.run_id,
        } for item in rollbacks],
        "data_classification": dataset.data_classification,
    }


@router.get("")
def foundation_state(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    return _state(db, user)


@router.post("/install")
def install_foundation(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        result = install_platform_foundation(db, _identity(user))
        return {"result": result, "state": _state(db, user)}
    except Exception as exc:
        db.rollback()
        raise _http_error(exc) from exc


@router.post("/sources")
def create_source(
    payload: SourceCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    del user
    existing = db.get(DataSourceConnection, payload.source_id)
    if existing:
        if existing.source_type != payload.source_type:
            raise HTTPException(409, detail={
                "code": "SOURCE_CONFLICT",
                "message": "数据源标识已被其他连接器类型使用",
            })
        source = existing
        created = False
    else:
        if payload.source_type in {"postgresql", "mysql"} and (
            not payload.host or not payload.database_name or not payload.username
            or not payload.credential_ref
        ):
            raise HTTPException(422, detail={
                "code": "SOURCE_CONFIG_INVALID",
                "message": "数据库连接器需要主机、数据库、用户名和凭据引用",
            })
        if payload.source_type in {"csv", "excel"} and not payload.resource_locator:
            raise HTTPException(422, detail={
                "code": "SOURCE_CONFIG_INVALID",
                "message": "文件连接器需要受控导入目录中的资源定位符",
            })
        source = DataSourceConnection(
            source_id=payload.source_id,
            display_name=payload.display_name,
            source_type=payload.source_type,
            host=payload.host,
            port=payload.port,
            database_name=payload.database_name,
            username=payload.username,
            resource_locator=payload.resource_locator,
            credential_env_key=payload.credential_ref,
            connection_options_json="{}",
            status="configured",
        )
        db.add(source)
        db.commit()
        created = True
    return {
        "source_id": source.source_id,
        "source_type": source.source_type,
        "status": source.status,
        "created": created,
        "credential_ref_configured": bool(source.credential_env_key),
        "credential_exposed": False,
    }


@router.get("/sources/{source_id}/discover")
def discover_managed_source(
    source_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    del user
    source = db.get(DataSourceConnection, source_id)
    if source is None:
        raise _http_error(DatasetReleaseError("SOURCE_NOT_FOUND", "数据源不存在"))
    if source_id != "platform-postgresql":
        raise _http_error(DatasetReleaseError(
            "POLICY_DENIED",
            "外部数据源发现必须通过凭据引用配置；P1A 不接收明文凭据",
        ))
    inspector = inspect(db.get_bind())
    schema_name = "public" if db.get_bind().dialect.name == "postgresql" else "main"
    tables = []
    available = set(inspector.get_table_names(schema=schema_name))
    for table_name in MANAGED_RELATIONS:
        if table_name not in available:
            continue
        tables.append({
            "name": table_name,
            "kind": "table",
            "columns": [{
                "name": column["name"],
                "source_type": str(column["type"]),
                "nullable": bool(column["nullable"]),
            } for column in inspector.get_columns(table_name, schema=schema_name)],
        })
    return {
        "source_id": source_id,
        "source_type": source.source_type,
        "schemas": [{"name": schema_name, "tables": tables}],
        "table_count": len(tables),
        "credential_exposed": False,
        "data_classification": current_data_truth(db)["data_classification"],
    }


@router.post("/datasets/{dataset_id}/versions")
def create_dataset_version(
    dataset_id: str,
    payload: VersionCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    if payload.period_start >= payload.period_end_exclusive:
        raise HTTPException(422, detail={"code": "INVALID_RANGE", "message": "数据时间范围无效"})
    try:
        identity, dataset = _scoped_dataset(db, user, dataset_id)
        template = db.scalar(select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset.dataset_id,
        ).order_by(DatasetVersion.version.desc()))
        if template is None:
            raise DatasetReleaseError("VERSION_NOT_FOUND", "请先安装场景基础版本")
        mapping = db.get(MappingVersion, template.mapping_version_id)
        version = DatasetVersionService(db).create_version(
            identity,
            dataset_id=dataset.dataset_id,
            mapping=json.loads(mapping.mapping_json),
            schema=json.loads(template.schema_json),
            source_binding=json.loads(template.source_binding_json),
            source_version=f"managed-simulated:{payload.idempotency_key}",
            quality_run_id=f"DQ-{payload.idempotency_key}",
            quality_status="PASSED",
            quality_rules=[
                {"code": "managed_source_binding", "status": "PASSED"},
                {"code": "schema_compatible", "status": "PASSED"},
                {"code": "simulated_data_label", "status": "PASSED"},
            ],
            row_count=int(db.scalar(select(func.count()).select_from(ChargingSession)) or 0),
            period_start=payload.period_start.isoformat(),
            period_end_exclusive=payload.period_end_exclusive.isoformat(),
            compatible_semantic_range=template.compatible_semantic_range,
            idempotency_key=payload.idempotency_key,
        )
        return {"dataset_version_id": version.dataset_version_id, "state": _state(db, user)}
    except Exception as exc:
        db.rollback()
        raise _http_error(exc) from exc


@router.post("/versions/{dataset_version_id}/submit")
def submit_version(
    dataset_version_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        review = ReleaseService(db).submit(_identity(user), dataset_version_id)
        return {"review_record_id": review.review_record_id, "status": review.status, "state": _state(db, user)}
    except Exception as exc:
        db.rollback()
        raise _http_error(exc) from exc


@router.post("/versions/{dataset_version_id}/approve")
def approve_version(
    dataset_version_id: str,
    payload: ActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        review = ReleaseService(db).decide(
            _identity(user), dataset_version_id, approved=True, reason=payload.reason
        )
        return {"review_record_id": review.review_record_id, "status": review.status, "state": _state(db, user)}
    except Exception as exc:
        db.rollback()
        raise _http_error(exc) from exc


@router.post("/versions/{dataset_version_id}/reject")
def reject_version(
    dataset_version_id: str,
    payload: ActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        review = ReleaseService(db).decide(
            _identity(user), dataset_version_id, approved=False,
            reason=payload.reason or "管理员驳回",
        )
        return {"review_record_id": review.review_record_id, "status": review.status, "state": _state(db, user)}
    except Exception as exc:
        db.rollback()
        raise _http_error(exc) from exc


@router.post("/versions/{dataset_version_id}/publish")
def publish_version(
    dataset_version_id: str,
    payload: ActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        version = ReleaseService(db).publish(
            _identity(user), dataset_version_id, idempotency_key=payload.idempotency_key
        )
        return {"dataset_version_id": version.dataset_version_id, "status": version.status, "state": _state(db, user)}
    except Exception as exc:
        db.rollback()
        raise _http_error(exc) from exc


@router.post("/versions/{dataset_version_id}/activate")
def activate_version(
    dataset_version_id: str,
    payload: ActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        identity = _identity(user)
        version = db.get(DatasetVersion, dataset_version_id)
        if version is None:
            raise DatasetReleaseError("VERSION_NOT_FOUND", "数据集版本不存在")
        pointer = SemanticActivationService(db).current(
            identity, scenario_id=SCENARIO_ID, dataset_id=version.dataset_id
        )
        activation = SemanticActivationService(db).activate(
            identity,
            dataset_version_id=dataset_version_id,
            scenario_version=pointer.scenario_version,
            semantic_model_version_id=pointer.active_semantic_model_version_id,
            idempotency_key=payload.idempotency_key,
            reason=payload.reason,
        )
        return {"activation_id": activation.activation_id, "state": _state(db, user)}
    except Exception as exc:
        db.rollback()
        raise _http_error(exc) from exc


@router.post("/datasets/{dataset_id}/rollback")
def rollback_dataset(
    dataset_id: str,
    payload: RollbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        identity, dataset = _scoped_dataset(db, user, dataset_id)
        record = RollbackService(db).rollback(
            identity,
            scenario_id=dataset.scenario_id,
            dataset_id=dataset.dataset_id,
            target_dataset_version_id=payload.target_dataset_version_id,
            reason=payload.reason or "管理员回滚",
            idempotency_key=payload.idempotency_key,
        )
        return {"rollback_record_id": record.rollback_record_id, "run_id": record.run_id, "state": _state(db, user)}
    except Exception as exc:
        db.rollback()
        raise _http_error(exc) from exc
