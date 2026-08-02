from __future__ import annotations

import json
import threading
import time
from typing import Protocol
from uuid import uuid4

import jwt
import httpx
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
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


class RemoteJWKSOIDCProvider:
    """Standards-based RS256 OIDC verifier with bounded JWKS caching."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        provider_code: str,
        timeout_seconds: float = 10.0,
        cache_ttl_seconds: int = 300,
        clock_skew_seconds: int = 30,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.jwks_url = jwks_url
        self.provider_code = provider_code
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.clock_skew_seconds = clock_skew_seconds
        self._keys: dict[str, object] = {}
        self._expires_at = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings):
        return cls(
            issuer=settings.oidc_issuer,
            audience=settings.oidc_client_id,
            jwks_url=f"{settings.oidc_internal_base_url}/protocol/openid-connect/certs",
            provider_code=settings.oidc_provider_code,
            timeout_seconds=settings.oidc_http_timeout_seconds,
            cache_ttl_seconds=settings.oidc_jwks_cache_ttl_seconds,
            clock_skew_seconds=settings.oidc_clock_skew_seconds,
        )

    def verify(self, id_token: str) -> OIDCClaims:
        return self.verify_with_nonce(id_token, expected_nonce=None)

    def verify_with_nonce(self, id_token: str, *, expected_nonce: str | None) -> OIDCClaims:
        try:
            header = jwt.get_unverified_header(id_token)
            if header.get("alg") != "RS256" or not header.get("kid"):
                raise IdentityResolutionError("OIDC_TOKEN_INVALID", "OIDC token 算法或 kid 不受支持")
            key = self._signing_key(str(header["kid"]))
            payload = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.clock_skew_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            if expected_nonce is not None and payload.get("nonce") != expected_nonce:
                raise IdentityResolutionError("OIDC_NONCE_MISMATCH", "OIDC nonce 不匹配")
            subject = str(payload["sub"])
        except IdentityResolutionError:
            raise
        except jwt.InvalidIssuerError as exc:
            raise IdentityResolutionError("OIDC_ISSUER_MISMATCH", "OIDC issuer 不匹配") from exc
        except jwt.InvalidAudienceError as exc:
            raise IdentityResolutionError("OIDC_AUDIENCE_MISMATCH", "OIDC audience 不匹配") from exc
        except jwt.ExpiredSignatureError as exc:
            raise IdentityResolutionError("OIDC_TOKEN_EXPIRED", "OIDC token 已过期") from exc
        except jwt.MissingRequiredClaimError as exc:
            raise IdentityResolutionError("OIDC_REQUIRED_CLAIM_MISSING", f"OIDC 必需 claim 缺失：{exc.claim}") from exc
        except jwt.ImmatureSignatureError as exc:
            raise IdentityResolutionError("OIDC_TOKEN_NOT_YET_VALID", "OIDC token 尚未生效") from exc
        except jwt.InvalidSignatureError as exc:
            raise IdentityResolutionError("OIDC_SIGNATURE_INVALID", "OIDC token 签名无效") from exc
        except jwt.DecodeError as exc:
            raise IdentityResolutionError("OIDC_TOKEN_MALFORMED", "OIDC token 格式无效") from exc
        except (jwt.PyJWTError, KeyError, TypeError, ValueError, httpx.HTTPError) as exc:
            raise IdentityResolutionError(
                "OIDC_TOKEN_INVALID", f"OIDC token 验证失败（{type(exc).__name__}）"
            ) from exc
        return OIDCClaims(
            issuer=self.issuer,
            subject=subject,
            tenant_hint=payload.get("tenant_id"),
            email=payload.get("email"),
            display_name=str(payload.get("name") or payload.get("preferred_username") or subject),
            groups=tuple(str(item).lstrip("/") for item in payload.get("groups", [])),
            attributes={
                "audience": self.audience,
                "workspace_id": payload.get("workspace_id"),
            },
        )

    def invalidate_cache(self) -> None:
        with self._lock:
            self._keys.clear()
            self._expires_at = 0.0

    def _signing_key(self, kid: str):
        now = time.monotonic()
        with self._lock:
            if now >= self._expires_at or kid not in self._keys:
                response = httpx.get(self.jwks_url, timeout=self.timeout_seconds)
                response.raise_for_status()
                payload = response.json()
                keys: dict[str, object] = {}
                for item in payload.get("keys", []):
                    if (
                        not item.get("kid")
                        or item.get("kty") != "RSA"
                        or item.get("use") not in {None, "sig"}
                        or item.get("alg") not in {None, "RS256"}
                    ):
                        continue
                    try:
                        keys[str(item["kid"])] = jwt.PyJWK.from_dict(item, algorithm="RS256").key
                    except jwt.PyJWKError:
                        continue
                self._keys = keys
                self._expires_at = now + self.cache_ttl_seconds
            key = self._keys.get(kid)
        if key is None:
            raise IdentityResolutionError("OIDC_SIGNING_KEY_NOT_FOUND", "OIDC signing key 不存在")
        return key


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
        return self.resolve_oidc_claims(provider.provider_code, claims, request_id=request_id)

    def resolve_oidc_claims(self, provider_code: str, claims: OIDCClaims, *, request_id: str) -> IdentityContext:
        principal = self.db.scalar(select(Principal).where(
            Principal.provider_code == provider_code,
            Principal.external_subject == claims.subject,
            Principal.status == "ACTIVE",
        ))
        if principal is None:
            raise IdentityResolutionError("OIDC_MAPPING_NOT_FOUND", "OIDC subject 没有预先审批的 Principal 映射")
        if claims.tenant_hint and claims.tenant_hint != principal.tenant_id:
            raise IdentityResolutionError("OIDC_TENANT_MISMATCH", "OIDC tenant 与已发布映射不一致")
        attributes = json.loads(principal.attributes_json)
        workspace_hint = claims.attributes.get("workspace_id")
        if workspace_hint and workspace_hint != principal.workspace_id:
            raise IdentityResolutionError("OIDC_WORKSPACE_MISMATCH", "OIDC workspace 与已发布映射不一致")
        required_groups = set(attributes.get("required_groups", []))
        if not required_groups.issubset(set(claims.groups)):
            raise IdentityResolutionError("OIDC_GROUP_MAPPING_DENIED", "OIDC group 未满足已发布映射")
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

    def resolve_oidc_session(
        self,
        *,
        principal_id: str,
        groups: tuple[str, ...],
        request_id: str,
    ) -> IdentityContext:
        principal = self.db.get(Principal, principal_id)
        if principal is None or principal.status != "ACTIVE" or not principal.provider_code.startswith("OIDC"):
            raise IdentityResolutionError("OIDC_MAPPING_NOT_FOUND", "OIDC Principal 映射不可用")
        attributes = json.loads(principal.attributes_json)
        if not set(attributes.get("required_groups", [])).issubset(set(groups)):
            raise IdentityResolutionError("OIDC_GROUP_MAPPING_DENIED", "OIDC group 映射已失效")
        return IdentityContext(
            subject_id=f"principal:{principal.principal_id}",
            tenant_id=principal.tenant_id,
            org_id=principal.organization_id,
            workspace_id=principal.workspace_id,
            roles=tuple(attributes.get("roles", [])),
            groups=groups,
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
                    provider_code = str(payload.get("auth_provider") or "LOCAL")
                    if provider_code == "LOCAL":
                        if not get_settings().local_auth_enabled:
                            raise IdentityResolutionError(
                                "LOCAL_AUTH_DISABLED",
                                "本环境不接受本地身份令牌",
                            )
                        identity = IdentityService(db).resolve_local(user, request_id=request_id)
                    else:
                        from app.preproduction.oidc import OIDCSessionStore

                        session_id = str(payload["sid"])
                        session = OIDCSessionStore().get_session(session_id)
                        if int(session["user_id"]) != user.id or session["principal_id"] != payload.get("principal_id"):
                            raise IdentityResolutionError("OIDC_SESSION_INVALID", "OIDC 会话映射不一致")
                        identity = IdentityService(db).resolve_oidc_session(
                            principal_id=str(session["principal_id"]),
                            groups=tuple(str(item) for item in session.get("groups", [])),
                            request_id=request_id,
                        )
                    request.state.authenticated_user_id = user.id
                    request.state.identity = identity
            except (jwt.PyJWTError, KeyError, ValueError, IdentityResolutionError, RuntimeError) as exc:
                request.state.identity_error = getattr(exc, "code", "INVALID_TOKEN")
        return await call_next(request)
