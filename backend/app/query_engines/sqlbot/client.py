import os
from time import perf_counter
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.query_engines.sqlbot.contracts import SQLBotHealth
from app.query_engines.sqlbot.credentials import derive_runtime_account_password
from app.query_engines.sqlbot.error_mapper import (
    SQLBotEngineError,
    SQLBotErrorCode,
    map_http_error,
)
from app.query_engines.sqlbot.health import CircuitBreaker


class SQLBotClient:
    def __init__(
        self,
        base_url: str,
        *,
        username_env_key: str | None = None,
        password_env_key: str | None = None,
        credential_loader: Callable[[], tuple[str, str]] | None = None,
        timeout_seconds: float,
        breaker: CircuitBreaker,
        transport: httpx.BaseTransport | None = None,
    ):
        self.username_env_key = username_env_key
        self.password_env_key = password_env_key
        self.credential_loader = credential_loader
        self.breaker = breaker
        parsed_base_url = urlsplit(base_url)
        self.health_url = urlunsplit((
            parsed_base_url.scheme,
            parsed_base_url.netloc,
            "/",
            "",
            "",
        ))
        self.http = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/",
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    def _credentials(self) -> tuple[str, str]:
        if self.credential_loader is not None:
            username, password = self.credential_loader()
            password = derive_runtime_account_password(password)
        else:
            username = os.getenv(self.username_env_key) if self.username_env_key else None
            password = os.getenv(self.password_env_key) if self.password_env_key else None
        if not username or not password:
            raise SQLBotEngineError(
                SQLBotErrorCode.NOT_CONFIGURED,
                "SQLBot 服务账号秘密引用未配置",
            )
        return username, password

    def _call(self, operation: Callable[[], httpx.Response]) -> dict:
        self.breaker.before_call()
        try:
            response = operation()
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise SQLBotEngineError(
                    SQLBotErrorCode.RESPONSE_INVALID,
                    "SQLBot HTTP 响应不是对象",
                )
        except SQLBotEngineError:
            self.breaker.record_failure()
            raise
        except Exception as exc:
            self.breaker.record_failure()
            raise map_http_error(exc) from exc
        self.breaker.record_success()
        return payload

    def create_session(self) -> tuple[str, str]:
        username, password = self._credentials()
        payload = self._call(
            lambda: self.http.post(
                "mcp/mcp_start",
                json={"username": username, "password": password},
            )
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        token = data.get("access_token")
        chat_id = data.get("chat_id")
        if not isinstance(token, str) or chat_id is None:
            raise SQLBotEngineError(
                SQLBotErrorCode.RESPONSE_INVALID,
                "SQLBot 会话响应缺少必要字段",
            )
        return str(chat_id), token

    def generate_sql(self, payload: dict) -> dict:
        """Call the governed SQLBot generate-only runtime extension."""
        return self._call(
            lambda: self.http.post("mcp/mcp_generate_sql", json=payload)
        )

    def record_usage(self, record_id: str, access_token: str) -> int | None:
        """Return SQLBot's recorded token total without exposing the session token."""
        try:
            response = self.http.get(
                f"chat/record/{record_id}/usage",
                headers={"X-SQLBOT-TOKEN": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
                payload = payload["data"]
            value = payload.get("total_tokens") if isinstance(payload, dict) else None
            return value if isinstance(value, int) else None
        except Exception:
            # Usage telemetry is optional evidence. Its failure must not turn a
            # guarded read-only query into a user-facing query failure.
            return None

    def health_check(self) -> SQLBotHealth:
        if self.breaker.status == "open":
            return SQLBotHealth(status="circuit_open")
        started = perf_counter()
        try:
            response = self.http.get(self.health_url)
            response.raise_for_status()
        except Exception:
            return SQLBotHealth(status="unavailable")
        return SQLBotHealth(
            status="ok",
            latency_ms=int((perf_counter() - started) * 1000),
        )

    def close(self) -> None:
        self.http.close()
