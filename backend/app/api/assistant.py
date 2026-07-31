from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.core.database import get_db
from app.models.auth import User
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
