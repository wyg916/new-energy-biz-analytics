from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.chatbi.compiler import ScopeDenied
from app.chatbi.guard import QueryRejected
from app.chatbi.plan import QUERY_PLAN_JSON_SCHEMA
from app.chatbi.service import ChatBIService
from app.core.database import get_db
from app.models.auth import User

router = APIRouter(prefix="/chat", tags=["chatbi"])


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@router.get("/query-plan-schema")
def query_plan_schema(_: User = Depends(current_user)) -> dict:
    return QUERY_PLAN_JSON_SCHEMA


@router.post("/query")
def query(payload: ChatRequest, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    try:
        return ChatBIService(db, user).ask(payload.question)
    except ScopeDenied:
        raise HTTPException(status_code=403, detail={"code": "AUTH_SCOPE_DENIED", "message": "请求范围不在当前授权范围内"})
    except QueryRejected:
        raise HTTPException(status_code=422, detail={"code": "QUERY_REJECTED", "message": "查询未通过安全校验"})
