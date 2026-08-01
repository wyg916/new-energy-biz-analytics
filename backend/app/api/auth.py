import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_roles, trusted_identity
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, decode_access_token, verify_password
from app.models.auth import AuditLog, User
from app.governance.audit import record_governance_event
from app.governance.identity import IdentityResolutionError, IdentityService
from app.platform.identity import IdentityContext
from app.preproduction.oidc import OIDCFlowError, OIDCFlowService

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class OIDCCallbackRequest(BaseModel):
    code: str = Field(min_length=8, max_length=4096)
    state: str = Field(min_length=16, max_length=256)


def user_view(user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role, "region_code": user.region_code}


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    if not get_settings().local_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "LOCAL_AUTH_DISABLED", "message": "本环境只允许企业身份登录"},
        )
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


def _oidc_error(exc: OIDCFlowError) -> HTTPException:
    unavailable = exc.code.endswith("UNAVAILABLE") or exc.code == "OIDC_NOT_CONFIGURED"
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE if unavailable else status.HTTP_401_UNAUTHORIZED,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.get("/oidc/status")
def oidc_status(db: Session = Depends(get_db)) -> dict:
    service = OIDCFlowService(db)
    return service.provider_health()


@router.post("/oidc/start")
def oidc_start(db: Session = Depends(get_db)) -> dict:
    try:
        return OIDCFlowService(db).start()
    except OIDCFlowError as exc:
        raise _oidc_error(exc) from exc


@router.post("/oidc/callback")
def oidc_callback(payload: OIDCCallbackRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    try:
        return OIDCFlowService(db).callback(
            code=payload.code,
            state=payload.state,
            request_id=request.headers.get("x-request-id") or "OIDC-CALLBACK",
        )
    except OIDCFlowError as exc:
        raise _oidc_error(exc) from exc


@router.post("/oidc/logout")
def oidc_logout(
    request: Request,
    identity: IdentityContext = Depends(trusted_identity),
    db: Session = Depends(get_db),
) -> dict:
    supplied = request.headers.get("authorization", "")
    try:
        payload = decode_access_token(supplied.split(" ", 1)[1])
        if payload.get("auth_provider") == "LOCAL" or not payload.get("sid"):
            raise OIDCFlowError("OIDC_SESSION_REQUIRED", "当前会话不是 OIDC 会话")
        return OIDCFlowService(db).logout(
            session_id=str(payload["sid"]),
            identity=identity,
            request_id=request.headers.get("x-request-id") or "OIDC-LOGOUT",
        )
    except (IndexError, KeyError, OIDCFlowError) as exc:
        flow_error = exc if isinstance(exc, OIDCFlowError) else OIDCFlowError("OIDC_SESSION_INVALID", "OIDC 会话无效")
        raise _oidc_error(flow_error) from exc


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_view(user)


@router.get("/admin-check")
def admin_check(user: User = Depends(require_roles("analyst_admin"))) -> dict:
    return {"ok": True, "user_id": user.id}
