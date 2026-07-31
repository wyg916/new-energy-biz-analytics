from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
import json
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.core.database import get_db
from app.models.auth import User
from app.models.auth import AuditLog
from app.orchestration.composite import CompositeQueryOrchestrator, CompositeRoute
from app.response.contracts import ResponseProfileName

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
    result = CompositeQueryOrchestrator(db, user).execute(
        payload.question,
        scenario_id=payload.scenario_id,
        profile=payload.profile,
        conversation_id=payload.conversation_id,
        requested_route=payload.route,
    )
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
        from fastapi import HTTPException

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
