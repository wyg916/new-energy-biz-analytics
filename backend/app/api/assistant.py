from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
import json
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.chatbi.compiler import ScopeDenied
from app.chatbi.guard import QueryRejected
from app.chatbi.memory import MemoryAccessDenied
from app.chatbi.scenario_services import ScenarioChatServiceError
from app.core.database import get_db
from app.models.auth import User
from app.models.auth import AuditLog
from app.orchestration.composite import CompositeQueryOrchestrator, CompositeRoute
from app.platform.scenario_packages import ScenarioPackageError
from app.platform.semantic_registry import SemanticRegistryError
from app.query_engines.router import QueryRoutingError
from app.response.contracts import ResponseProfileName
from app.scenarios.sales_ops.engine import SalesOpsQueryError

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=1000)
    scenario_id: str = Field(default="charging_ops", pattern=r"^(charging_ops|sales_ops)$")
    profile: ResponseProfileName = ResponseProfileName.EXECUTIVE_BRIEF
    conversation_id: str | None = Field(default=None, max_length=48)
    route: CompositeRoute | None = None


class AssistantFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=8, max_length=96)
    trace_id: str = Field(min_length=8, max_length=96)
    rating: str = Field(pattern=r"^(helpful|not_helpful)$")
    comment: str | None = Field(default=None, max_length=500)


@router.post("/query")
def assistant_query(
    payload: AssistantQueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        result = CompositeQueryOrchestrator(db, user).execute(
            payload.question,
            scenario_id=payload.scenario_id,
            profile=payload.profile,
            conversation_id=payload.conversation_id,
            requested_route=payload.route,
        )
    except (ScopeDenied, MemoryAccessDenied):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "AUTH_SCOPE_DENIED",
                "message": "请求范围不在当前授权范围内",
            },
        )
    except ScenarioChatServiceError as exc:
        status_code = 403 if exc.code in {
            "CONVERSATION_SCOPE_DENIED",
            "CONVERSATION_SCENARIO_MISMATCH",
        } else 404
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
        raise HTTPException(
            status_code=422,
            detail={"code": "QUERY_REJECTED", "message": "查询未通过安全校验"},
        )
    except (ScenarioPackageError, SemanticRegistryError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return {
        "route": result.route,
        "response": result.response,
        "data_query_evidence": result.data_query_evidence,
        "knowledge_retrieval_evidence": result.knowledge_retrieval_evidence,
        "model_call": result.model_call,
        "trace_id": result.trace_id,
        "run_id": result.run_id,
        "conversation_id": result.conversation_id,
        "data_classification": "simulated",
    }


@router.post("/feedback")
def assistant_feedback(
    payload: AssistantFeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    source = db.query(AuditLog).filter(
        AuditLog.actor_user_id == user.id,
        AuditLog.resource == f"composite_query:{payload.run_id}",
    ).first()
    if source is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "COMPOSITE_RUN_NOT_FOUND", "message": "未找到当前身份范围内的复合查询运行记录"},
        )
    db.add(AuditLog(
        actor_user_id=user.id,
        action="assistant.feedback",
        resource=f"composite_query:{payload.run_id}",
        outcome=payload.rating,
        detail_json=json.dumps({
            "trace_id": payload.trace_id,
            "comment": payload.comment,
        }, ensure_ascii=False),
    ))
    db.commit()
    return {"status": "recorded", "rating": payload.rating, "run_id": payload.run_id}
