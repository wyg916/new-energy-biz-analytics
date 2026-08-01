from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.governance.audit import record_governance_event
from app.governance.identity import IdentityResolutionError, IdentityService, RemoteJWKSOIDCProvider
from app.governance.models import Principal
from app.models.auth import User


class OIDCFlowError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OIDCTransaction:
    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str


class OIDCSessionStore:
    """Redis-backed one-time authorization transactions and revocable sessions."""

    def __init__(self, client: Redis | None = None, *, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or Redis.from_url(self.settings.redis_url, decode_responses=True)

    def create_transaction(self, redirect_uri: str) -> OIDCTransaction:
        transaction = OIDCTransaction(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            code_verifier=secrets.token_urlsafe(64),
            redirect_uri=redirect_uri,
        )
        payload = json.dumps(transaction.__dict__, sort_keys=True)
        self.client.setex(
            self._transaction_key(transaction.state),
            self.settings.oidc_transaction_ttl_seconds,
            payload,
        )
        return transaction

    def consume_transaction(self, state: str) -> OIDCTransaction:
        try:
            payload = self.client.getdel(self._transaction_key(state))
        except Exception as exc:
            raise OIDCFlowError("OIDC_STATE_STORE_UNAVAILABLE", "OIDC 状态存储不可用") from exc
        if not payload:
            raise OIDCFlowError("OIDC_STATE_INVALID", "OIDC state 无效、过期或已使用")
        try:
            return OIDCTransaction(**json.loads(payload))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OIDCFlowError("OIDC_STATE_INVALID", "OIDC state 无效") from exc

    def create_session(
        self,
        *,
        principal_id: str,
        user_id: int,
        groups: tuple[str, ...],
        refresh_token: str,
    ) -> str:
        session_id = f"OIDC-{secrets.token_urlsafe(32)}"
        self.client.setex(
            self._session_key(session_id),
            self.settings.oidc_session_ttl_seconds,
            json.dumps({
                "principal_id": principal_id,
                "user_id": user_id,
                "groups": list(groups),
                "refresh_token": refresh_token,
            }, sort_keys=True),
        )
        return session_id

    def get_session(self, session_id: str) -> dict:
        try:
            payload = self.client.get(self._session_key(session_id))
        except Exception as exc:
            raise OIDCFlowError("OIDC_SESSION_STORE_UNAVAILABLE", "OIDC 会话存储不可用") from exc
        if not payload:
            raise OIDCFlowError("OIDC_SESSION_INVALID", "OIDC 会话无效或已注销")
        return dict(json.loads(payload))

    def revoke_session(self, session_id: str) -> dict:
        session = self.get_session(session_id)
        self.client.delete(self._session_key(session_id))
        return session

    def health(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    @staticmethod
    def _transaction_key(state: str) -> str:
        return f"p4:oidc:transaction:{state}"

    @staticmethod
    def _session_key(session_id: str) -> str:
        return f"p4:oidc:session:{session_id}"


class OIDCFlowService:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings | None = None,
        store: OIDCSessionStore | None = None,
        provider: RemoteJWKSOIDCProvider | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.store = store or OIDCSessionStore(settings=self.settings)
        self.provider = provider or RemoteJWKSOIDCProvider.from_settings(self.settings)
        self.client = client or httpx.Client(timeout=self.settings.oidc_http_timeout_seconds)

    def start(self) -> dict:
        self._require_enabled()
        transaction = self.store.create_transaction(self.settings.oidc_redirect_uri)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(transaction.code_verifier.encode()).digest()
        ).decode().rstrip("=")
        query = urlencode({
            "client_id": self.settings.oidc_client_id,
            "redirect_uri": transaction.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.settings.oidc_scope_list),
            "state": transaction.state,
            "nonce": transaction.nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return {
            "authorization_url": f"{self.settings.oidc_issuer}/protocol/openid-connect/auth?{query}",
            "state": transaction.state,
            "expires_in": self.settings.oidc_transaction_ttl_seconds,
            "provider": self.settings.oidc_provider_code,
        }

    def callback(self, *, code: str, state: str, request_id: str) -> dict:
        self._require_enabled()
        transaction = self.store.consume_transaction(state)
        try:
            response = self.client.post(
                f"{self.settings.oidc_internal_base_url}/protocol/openid-connect/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.settings.oidc_client_id,
                    "redirect_uri": transaction.redirect_uri,
                    "code": code,
                    "code_verifier": transaction.code_verifier,
                },
            )
            response.raise_for_status()
            token_payload = response.json()
            id_token = str(token_payload["id_token"])
            refresh_token = str(token_payload["refresh_token"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise OIDCFlowError("OIDC_CODE_EXCHANGE_FAILED", "OIDC 授权码交换失败") from exc
        try:
            claims = self.provider.verify_with_nonce(id_token, expected_nonce=transaction.nonce)
            identity = IdentityService(self.db).resolve_oidc_claims(
                self.provider.provider_code,
                claims,
                request_id=request_id,
            )
        except IdentityResolutionError as exc:
            raise OIDCFlowError(exc.code, str(exc)) from exc
        principal = self.db.get(Principal, identity.principal_id)
        user = self.db.get(User, principal.local_user_id) if principal and principal.local_user_id else None
        if user is None or not user.is_active:
            raise OIDCFlowError("OIDC_LOCAL_USER_DISABLED", "OIDC 映射用户不可用")
        session_id = self.store.create_session(
            principal_id=principal.principal_id,
            user_id=user.id,
            groups=claims.groups,
            refresh_token=refresh_token,
        )
        record_governance_event(
            self.db,
            identity,
            action="auth.oidc_login",
            resource_type="session",
            resource_id=session_id,
            result="SUCCESS",
            trace_id=request_id,
            detail={"provider": self.provider.provider_code, "groups": list(claims.groups)},
            commit=True,
        )
        return {
            "access_token": create_access_token(
                user.id,
                user.role,
                auth_provider=self.provider.provider_code,
                principal_id=principal.principal_id,
                session_id=session_id,
            ),
            "token_type": "bearer",
            "provider": self.provider.provider_code,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "role": user.role,
                "tenant_id": identity.tenant_id,
                "workspace_id": identity.workspace_id,
                "groups": list(identity.groups),
            },
        }

    def logout(self, *, session_id: str, identity, request_id: str) -> dict:
        session = self.store.revoke_session(session_id)
        upstream = True
        try:
            response = self.client.post(
                f"{self.settings.oidc_internal_base_url}/protocol/openid-connect/logout",
                data={
                    "client_id": self.settings.oidc_client_id,
                    "refresh_token": session["refresh_token"],
                },
            )
            response.raise_for_status()
        except (httpx.HTTPError, KeyError):
            upstream = False
        record_governance_event(
            self.db,
            identity,
            action="auth.oidc_logout",
            resource_type="session",
            resource_id=session_id,
            result="SUCCESS" if upstream else "PARTIAL",
            trace_id=request_id,
            detail={"upstream_session_invalidated": upstream},
            commit=True,
        )
        return {"logged_out": True, "upstream_session_invalidated": upstream}

    def provider_health(self) -> dict:
        if not self.settings.oidc_enabled:
            return {"configured": False, "status": "CONDITIONAL"}
        started = time.perf_counter()
        try:
            response = self.client.get(
                f"{self.settings.oidc_internal_base_url}/.well-known/openid-configuration"
            )
            response.raise_for_status()
            discovery = response.json()
            ok = discovery.get("issuer") == self.settings.oidc_issuer
        except (httpx.HTTPError, ValueError):
            ok = False
        return {
            "configured": True,
            "status": "READY" if ok and self.store.health() else "UNAVAILABLE",
            "provider": self.settings.oidc_provider_code,
            "issuer": self.settings.oidc_issuer,
            "client_id": self.settings.oidc_client_id,
            "pkce_method": "S256",
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    def _require_enabled(self) -> None:
        if not self.settings.oidc_enabled:
            raise OIDCFlowError("OIDC_NOT_CONFIGURED", "OIDC 尚未配置")
