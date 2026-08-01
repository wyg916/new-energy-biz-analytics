from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import get_settings
from app.governance.authorization import AuthorizationService, request_context
from app.models.auth import User
from app.platform.identity import IdentityContext

bearer = HTTPBearer(auto_error=False)


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "AUTH_REQUIRED", "message": "需要登录"})
    user_id = getattr(request.state, "authenticated_user_id", None)
    user = db.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "INVALID_TOKEN", "message": "登录状态无效"})
    return user


def trusted_identity(request: Request, _: User = Depends(current_user)) -> IdentityContext:
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": getattr(request.state, "identity_error", None) or "IDENTITY_REQUIRED", "message": "服务端身份映射失败"},
        )
    return identity


def require_permission(action: str, resource_type: str) -> Callable:
    def dependency(
        identity: IdentityContext = Depends(trusted_identity),
        db: Session = Depends(get_db),
    ) -> IdentityContext:
        decision = AuthorizationService(db, identity).decide(request_context(
            identity,
            action=action,
            resource_type=resource_type,
            environment=get_settings().app_env,
        ))
        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": decision.code, "message": decision.reason},
            )
        return identity
    return dependency


def require_roles(*roles: str) -> Callable:
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN", "message": "权限不足"})
        return user
    return dependency
