from fastapi import APIRouter, Depends, HTTPException
import json
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, trusted_identity
from app.chatbi.compiler import ScopeDenied
from app.chatbi.guard import QueryRejected
from app.chatbi.plan import QUERY_PLAN_JSON_SCHEMA
from app.chatbi.memory import MemoryAccessDenied, SessionMemory
from app.chatbi.scenario_services import (
    ScenarioChatServiceError,
    get_scenario_chat_registry,
)
from app.core.database import get_db
from app.models.auth import AuditLog, User
from app.models.query_routing import QueryRouteDecisionRecord
from app.platform.identity import IdentityContextFactory
from app.platform.scenario_packages import ScenarioPackageError
from app.platform.semantic_registry import SemanticRegistryError
from app.query_engines.router import QueryRoutingError
from app.scenarios.sales_ops.engine import SalesOpsQueryError
from app.core.config import get_settings
from app.governance.audit import record_governance_event
from app.governance.authorization import AuthorizationDenied, AuthorizationService, request_context
from app.platform.identity import IdentityContext

router = APIRouter(prefix="/chat", tags=["chatbi"])


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    conversation_id: str | None = Field(default=None, max_length=48)
    scenario_id: str = Field(
        default="charging_ops",
        pattern=r"^[a-z][a-z0-9_]{1,63}$",
    )


class ChatFeedbackRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=48)
    run_id: str = Field(min_length=1, max_length=64)
    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    rating: Literal["helpful", "not_helpful"]
    comment: str | None = Field(default=None, max_length=500)


@router.get("/query-plan-schema")
def query_plan_schema(_: User = Depends(current_user)) -> dict:
    return QUERY_PLAN_JSON_SCHEMA


@router.get("/scenarios")
def scenarios(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    identity: IdentityContext = Depends(trusted_identity),
) -> dict:
    try:
        AuthorizationService(db, identity).require(request_context(
            identity, action="dataset.view", resource_type="dataset",
            environment=get_settings().app_env,
        ))
    except AuthorizationDenied as exc:
        raise HTTPException(403, detail={"code": exc.code, "message": str(exc)}) from exc
    return {
        "data_classification": "simulated",
        "scenarios": get_scenario_chat_registry().catalog(db, user),
    }


@router.post("/query")
def query(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    identity: IdentityContext = Depends(trusted_identity),
) -> dict:
    try:
        for action, resource_type in (
            ("datasource.view", "datasource"),
            ("dataset.view", "dataset"),
            ("metric.query", "metric"),
        ):
            AuthorizationService(db, identity).require(request_context(
                identity,
                action=action,
                resource_type=resource_type,
                scenario_id=payload.scenario_id,
                environment=get_settings().app_env,
            ))
        return get_scenario_chat_registry().execute(
            db,
            user,
            scenario_id=payload.scenario_id,
            conversation_id=payload.conversation_id,
            question=payload.question,
        )
    except AuthorizationDenied as exc:
        raise HTTPException(status_code=403, detail={"code": exc.code, "message": str(exc)}) from exc
    except (ScopeDenied, MemoryAccessDenied):
        raise HTTPException(status_code=403, detail={"code": "AUTH_SCOPE_DENIED", "message": "请求范围不在当前授权范围内"})
    except ScenarioChatServiceError as exc:
        status_code = (
            403
            if exc.code in {
                "CONVERSATION_SCOPE_DENIED",
                "CONVERSATION_SCENARIO_MISMATCH",
            }
            else 404
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except SalesOpsQueryError as exc:
        status_code = 403 if exc.code == "AUTH_SCOPE_DENIED" else 422
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except QueryRoutingError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except QueryRejected:
        record_governance_event(
            db, identity,
            action="sql.guard_violation",
            resource_type="metric",
            resource_id=payload.scenario_id,
            result="DENIED",
            detail={"scenario_id": payload.scenario_id},
            commit=True,
        )
        raise HTTPException(status_code=422, detail={"code": "QUERY_REJECTED", "message": "查询未通过安全校验"})
    except (ScenarioPackageError, SemanticRegistryError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/feedback")
def feedback(
    payload: ChatFeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    registry = get_scenario_chat_registry()
    try:
        binding = registry.validate_conversation_owner(
            db,
            user,
            payload.conversation_id,
        )
    except ScenarioChatServiceError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    if binding.scenario_id != payload.scenario_id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "CONVERSATION_SCENARIO_MISMATCH",
                "message": "反馈场景与会话绑定不一致",
            },
        )
    identity = IdentityContextFactory.from_user(user)
    route = db.scalar(select(QueryRouteDecisionRecord).where(
        QueryRouteDecisionRecord.run_id == payload.run_id,
        QueryRouteDecisionRecord.scenario == payload.scenario_id,
        QueryRouteDecisionRecord.subject_id == identity.subject_id,
    ))
    if route is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "QUERY_RUN_NOT_FOUND",
                "message": "未找到当前身份范围内的查询运行",
            },
        )
    db.add(AuditLog(
        actor_user_id=user.id,
        action="chat.feedback",
        resource=f"chat_query:{payload.run_id}",
        outcome=payload.rating,
        detail_json=json.dumps({
            "conversation_id": payload.conversation_id,
            "scenario_id": payload.scenario_id,
            "run_id": payload.run_id,
            "comment": payload.comment,
        }, ensure_ascii=False),
    ))
    db.commit()
    return {
        "status": "recorded",
        "rating": payload.rating,
        "run_id": payload.run_id,
    }


@router.delete("/sessions/{conversation_id}")
def clear_session(conversation_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    try:
        get_scenario_chat_registry().validate_conversation_owner(
            db,
            user,
            conversation_id,
        )
        SessionMemory(db, user, conversation_id).clear()
    except (MemoryAccessDenied, ScenarioChatServiceError):
        raise HTTPException(status_code=403, detail={"code": "AUTH_SCOPE_DENIED", "message": "会话不可访问"})
    return {"status": "cleared", "conversation_id": conversation_id}
