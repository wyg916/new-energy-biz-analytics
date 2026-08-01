from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.memory.audit import audit_memory_use
from app.platform.identity import IdentityContext


SECRET_MARKERS = (
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "database_url",
    "connection_string",
)


class WorkingMemoryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RedisWorkingClient(Protocol):
    def get(self, key: str) -> bytes | str | None: ...
    def set(self, key: str, value: str, *, ex: int) -> Any: ...
    def delete(self, key: str) -> int: ...
    def sadd(self, key: str, *values: str) -> int: ...
    def srem(self, key: str, *values: str) -> int: ...


class WorkingMemoryState(BaseModel):
    scenario_id: str
    dataset_version: str | None = None
    semantic_version: str | None = None
    time_range: dict[str, Any] | None = None
    metrics: list[str] = Field(default_factory=list, max_length=32)
    dimensions: list[str] = Field(default_factory=list, max_length=32)
    filters: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    chart_type: str | None = None
    query_result_summary: dict[str, Any] | None = None
    knowledge_references: list[str] = Field(default_factory=list, max_length=20)
    sqlbot_session_binding: str | None = None
    pending_task_dag: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    response_profile: str = "executive_brief"
    comparison: dict[str, Any] | None = None
    current_intent: str | None = None
    run_id: str | None = None
    state_version: int = 1
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkingMemoryResult(BaseModel):
    status: str
    storage: str
    key_digest: str
    state: WorkingMemoryState | None = None
    idempotent: bool = False
    reason: str | None = None


def _contains_secret(value: Any, path: str = "") -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            child_path = f"{path}.{key}" if path else str(key)
            if any(marker in normalized for marker in SECRET_MARKERS):
                return child_path
            found = _contains_secret(nested, child_path)
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _contains_secret(nested, f"{path}[{index}]")
            if found:
                return found
    return None


def working_registry_key(identity: IdentityContext) -> str:
    digest = hashlib.sha256(
        "|".join(
            (identity.tenant_id, identity.workspace_id, identity.subject_id)
        ).encode("utf-8")
    ).hexdigest()
    return f"chatbi:working-registry:v1:{digest}"


class WorkingMemoryService:
    MAX_BYTES = 64 * 1024

    def __init__(
        self,
        db: Session,
        identity: IdentityContext,
        *,
        redis_client: RedisWorkingClient | None = None,
        ttl_seconds: int = 7200,
    ) -> None:
        if ttl_seconds < 60 or ttl_seconds > 7 * 24 * 3600:
            raise ValueError("working memory TTL must be between 60 seconds and 7 days")
        self.db = db
        self.identity = identity
        self.ttl_seconds = ttl_seconds
        self.redis_client = redis_client

    @classmethod
    def from_runtime(
        cls,
        db: Session,
        identity: IdentityContext,
        *,
        ttl_seconds: int = 7200,
    ) -> "WorkingMemoryService":
        settings = get_settings()
        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            decode_responses=True,
        )
        return cls(db, identity, redis_client=client, ttl_seconds=ttl_seconds)

    def _key(self, *, scenario_id: str, session_id: str) -> str:
        parts = (
            self.identity.tenant_id,
            self.identity.workspace_id,
            self.identity.subject_id,
            scenario_id,
            session_id,
        )
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
        return f"chatbi:working:v1:{digest}"

    @staticmethod
    def _key_digest(key: str) -> str:
        return key.rsplit(":", 1)[-1]

    def load(self, *, scenario_id: str, session_id: str) -> WorkingMemoryResult:
        key = self._key(scenario_id=scenario_id, session_id=session_id)
        if self.redis_client is None:
            return self._degraded("REDIS_CLIENT_UNAVAILABLE", key, "working.load")
        try:
            raw = self.redis_client.get(key)
            if raw is None:
                audit_memory_use(
                    self.db,
                    self.identity,
                    action="working.load",
                    outcome="miss",
                    detail={"key_digest": self._key_digest(key), "scenario_id": scenario_id},
                    commit=True,
                )
                return WorkingMemoryResult(
                    status="MISS", storage="REDIS", key_digest=self._key_digest(key)
                )
            state = WorkingMemoryState.model_validate_json(raw)
            if state.scenario_id != scenario_id:
                raise WorkingMemoryError("WORKING_SCENARIO_MISMATCH", "工作记忆场景不匹配")
            audit_memory_use(
                self.db,
                self.identity,
                action="working.load",
                outcome="success",
                run_id=state.run_id,
                detail={"key_digest": self._key_digest(key), "scenario_id": scenario_id},
                commit=True,
            )
            return WorkingMemoryResult(
                status="AVAILABLE",
                storage="REDIS",
                key_digest=self._key_digest(key),
                state=state,
            )
        except WorkingMemoryError:
            raise
        except Exception as exc:
            return self._degraded(type(exc).__name__, key, "working.load")

    def save(
        self,
        *,
        session_id: str,
        state: WorkingMemoryState,
    ) -> WorkingMemoryResult:
        payload = state.model_dump(mode="json")
        secret_path = _contains_secret(payload)
        if secret_path:
            audit_memory_use(
                self.db,
                self.identity,
                action="working.save",
                outcome="rejected",
                run_id=state.run_id,
                reason="SECRET_FIELD_REJECTED",
                detail={"field_path": secret_path},
                commit=True,
            )
            raise WorkingMemoryError("SECRET_FIELD_REJECTED", "工作记忆禁止包含密钥或凭据字段")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > self.MAX_BYTES:
            raise WorkingMemoryError("WORKING_MEMORY_TOO_LARGE", "工作记忆超过 64 KiB 上限")
        key = self._key(scenario_id=state.scenario_id, session_id=session_id)
        if self.redis_client is None:
            return self._degraded("REDIS_CLIENT_UNAVAILABLE", key, "working.save", state.run_id)
        try:
            current = self.redis_client.get(key)
            idempotent = current == encoded
            if not idempotent:
                self.redis_client.set(key, encoded, ex=self.ttl_seconds)
                self.redis_client.sadd(working_registry_key(self.identity), key)
            audit_memory_use(
                self.db,
                self.identity,
                action="working.save",
                outcome="idempotent" if idempotent else "success",
                run_id=state.run_id,
                detail={
                    "key_digest": self._key_digest(key),
                    "scenario_id": state.scenario_id,
                    "ttl_seconds": self.ttl_seconds,
                    "state_version": state.state_version,
                },
                commit=True,
            )
            return WorkingMemoryResult(
                status="AVAILABLE",
                storage="REDIS",
                key_digest=self._key_digest(key),
                state=state,
                idempotent=idempotent,
            )
        except Exception as exc:
            return self._degraded(type(exc).__name__, key, "working.save", state.run_id)

    def close(self, *, scenario_id: str, session_id: str, run_id: str | None = None) -> WorkingMemoryResult:
        key = self._key(scenario_id=scenario_id, session_id=session_id)
        if self.redis_client is None:
            return self._degraded("REDIS_CLIENT_UNAVAILABLE", key, "working.close", run_id)
        try:
            self.redis_client.delete(key)
            self.redis_client.srem(working_registry_key(self.identity), key)
            audit_memory_use(
                self.db,
                self.identity,
                action="working.close",
                outcome="success",
                run_id=run_id,
                detail={"key_digest": self._key_digest(key), "scenario_id": scenario_id},
                commit=True,
            )
            return WorkingMemoryResult(
                status="CLEARED", storage="REDIS", key_digest=self._key_digest(key)
            )
        except Exception as exc:
            return self._degraded(type(exc).__name__, key, "working.close", run_id)

    def _degraded(
        self,
        reason: str,
        key: str,
        action: str,
        run_id: str | None = None,
    ) -> WorkingMemoryResult:
        audit_memory_use(
            self.db,
            self.identity,
            action=action,
            outcome="degraded",
            run_id=run_id,
            reason=reason,
            detail={"key_digest": self._key_digest(key)},
            commit=True,
        )
        return WorkingMemoryResult(
            status="DEGRADED",
            storage="NONE",
            key_digest=self._key_digest(key),
            reason=reason,
        )
