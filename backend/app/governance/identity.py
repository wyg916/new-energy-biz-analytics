from __future__ import annotations

import json
from typing import Protocol
from uuid import uuid4

import jwt
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.governance.contracts import OIDCClaims
from app.governance.models import Principal
from app.models.auth import User
from app.platform.identity import IdentityContext, IdentityContextFactory


class IdentityResolutionError(PermissionError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OIDCProvider(Protocol):
    provider_code: str

    def verify(self, id_token: str) -> OIDCClaims: ...


class SignedLocalOIDCProvider:
    """Testable OIDC adapter for isolated development; no enterprise IdP network call."""

    def __init__(self, *, issuer: str, audience: str, signing_key: str, provider_code: str = "OIDC_LOCAL") -> None:
        self.issuer = issuer
        self.audience = audience
        self.signing_key = signing_key
        self.provider_code = provider_code

    def verify(self, id_token: str) -> OIDCClaims:
        try:
            payload = jwt.decode(
                id_token,
                self.signing_key,
                algorithms=["HS256"],
                audience=self.audience,
                issuer=self.issuer,
            )
            subject = str(payload["sub"])
        except (jwt.PyJWTError, KeyError, TypeError) as exc:
            raise IdentityResolutionError("OIDC_TOKEN_INVALID", "OIDC token 验证失败") from exc
        return OIDCClaims(
            issuer=self.issuer,
            subject=subject,
            tenant_hint=payload.get("tenant_id"),
            email=payload.get("email"),
            display_name=str(payload.get("name") or subject),
            groups=tuple(str(item) for item in payload.get("groups", [])),
            attributes={"audience": self.audience},
        )


class IdentityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve_local(self, user: User, *, request_id: str) -> IdentityContext:
        principal = self.db.scalar(select(Principal).where(
            Principal.provider_code == "LOCAL",
            Principal.local_user_id == user.id,
            Principal.status == "ACTIVE",
        ))
        if principal is None:
            raise IdentityResolutionError("PRINCIPAL_MAPPING_NOT_FOUND", "本地用户没有 ACTIVE Principal 映射")
        identity = IdentityContextFactory.from_user(user, request_id=request_id)
        return IdentityContext(
            **{**identity.__dict__, "principal_id": principal.principal_id, "provider_code": principal.provider_code}
        )

    def resolve_oidc(self, provider: OIDCProvider, id_token: str, *, request_id: str) -> IdentityContext:
        claims = provider.verify(id_token)
        principal = self.db.scalar(select(Principal).where(
            Principal.provider_code == provider.provider_code,
            Principal.external_subject == claims.subject,
            Principal.status == "ACTIVE",
        ))
        if principal is None:
            raise IdentityResolutionError("OIDC_MAPPING_NOT_FOUND", "OIDC subject 没有预先审批的 Principal 映射")
        if claims.tenant_hint and claims.tenant_hint != principal.tenant_id:
            raise IdentityResolutionError("OIDC_TENANT_MISMATCH", "OIDC tenant 与已发布映射不一致")
        attributes = json.loads(principal.attributes_json)
        return IdentityContext(
            subject_id=f"principal:{principal.principal_id}",
            tenant_id=principal.tenant_id,
            org_id=principal.organization_id,
            workspace_id=principal.workspace_id,
            roles=tuple(attributes.get("roles", [])),
            groups=claims.groups,
            data_scopes=tuple(attributes.get("data_scopes", ["workspace:all"])),
            auth_strength=principal.auth_strength,
            issued_at=IdentityContextFactory.now(),
            request_id=request_id,
            principal_id=principal.principal_id,
            provider_code=principal.provider_code,
        )


class TrustedIdentityMiddleware(BaseHTTPMiddleware):
    """Resolve identity only from a verified bearer token and server-side mappings."""

    async def dispatch(self, request: Request, call_next):
        request.state.authenticated_user_id = None
        request.state.identity = None
        request.state.identity_error = None
        supplied = request.headers.get("authorization", "")
        request_id = request.headers.get("x-request-id") or f"REQ-{uuid4()}"
        if supplied.lower().startswith("bearer "):
            token = supplied.split(" ", 1)[1].strip()
            try:
                payload = decode_access_token(token)
                user_id = int(payload["sub"])
                with SessionLocal() as db:
                    user = db.get(User, user_id)
                    if user is None or not user.is_active:
                        raise IdentityResolutionError("INVALID_TOKEN", "登录状态无效")
                    identity = IdentityService(db).resolve_local(user, request_id=request_id)
                    request.state.authenticated_user_id = user.id
                    request.state.identity = identity
            except (jwt.PyJWTError, KeyError, ValueError, IdentityResolutionError) as exc:
                request.state.identity_error = getattr(exc, "code", "INVALID_TOKEN")
        return await call_next(request)
