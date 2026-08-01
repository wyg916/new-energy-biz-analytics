import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_roles
from app.core.database import get_db
from app.core.security import create_access_token, verify_password
from app.models.auth import AuditLog, User
from app.governance.audit import record_governance_event
from app.governance.identity import IdentityResolutionError, IdentityService

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


def user_view(user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role, "region_code": user.region_code}


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.username == payload.username))
    ok = bool(user and user.is_active and verify_password(payload.password, user.password_hash))
    db.add(AuditLog(actor_user_id=user.id if user else None, action="auth.login", resource="session", outcome="success" if ok else "denied", detail_json=json.dumps({"username": payload.username})))
    db.commit()
    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "INVALID_CREDENTIALS", "message": "用户名或密码错误"})
    try:
        identity = IdentityService(db).resolve_local(
            user,
            request_id=request.headers.get("x-request-id") or "LOGIN",
        )
    except IdentityResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": exc.code, "message": "身份映射未发布"},
        ) from exc
    record_governance_event(
        db,
        identity,
        action="auth.login",
        resource_type="session",
        resource_id=None,
        result="SUCCESS",
        detail={"provider": identity.provider_code, "auth_strength": identity.auth_strength},
        commit=True,
    )
    return {"access_token": create_access_token(user.id, user.role), "token_type": "bearer", "user": user_view(user)}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_view(user)


@router.get("/admin-check")
def admin_check(user: User = Depends(require_roles("analyst_admin"))) -> dict:
    return {"ok": True, "user_id": user.id}
