from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.chatbi.compiler import ScopeDenied
from app.chatbi.guard import QueryRejected
from app.chatbi.plan import QUERY_PLAN_JSON_SCHEMA
from app.chatbi.memory import MemoryAccessDenied, SessionMemory
from app.chatbi.service import ChatBIService
from app.core.database import get_db
from app.models.auth import User
from app.platform.scenario_packages import ScenarioPackageError
from app.platform.semantic_registry import SemanticRegistryError

router = APIRouter(prefix="/chat", tags=["chatbi"])


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    conversation_id: str | None = Field(default=None, max_length=48)


@router.get("/query-plan-schema")
def query_plan_schema(_: User = Depends(current_user)) -> dict:
    return QUERY_PLAN_JSON_SCHEMA


@router.post("/query")
def query(payload: ChatRequest, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    try:
        return ChatBIService(db, user, payload.conversation_id).ask(payload.question)
    except (ScopeDenied, MemoryAccessDenied):
        raise HTTPException(status_code=403, detail={"code": "AUTH_SCOPE_DENIED", "message": "请求范围不在当前授权范围内"})
    except QueryRejected:
        raise HTTPException(status_code=422, detail={"code": "QUERY_REJECTED", "message": "查询未通过安全校验"})
    except (ScenarioPackageError, SemanticRegistryError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.delete("/sessions/{conversation_id}")
def clear_session(conversation_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    try:
        SessionMemory(db, user, conversation_id).clear()
    except MemoryAccessDenied:
        raise HTTPException(status_code=403, detail={"code": "AUTH_SCOPE_DENIED", "message": "会话不可访问"})
    return {"status": "cleared", "conversation_id": conversation_id}
