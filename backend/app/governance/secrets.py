from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
import httpx

from app.core.config import get_settings
from app.governance.audit import record_governance_event
from app.governance.authorization import AuthorizationService, request_context
from app.governance.contracts import CredentialStatus, SecretValue
from app.governance.models import CredentialReference, CredentialUsageAudit
from app.platform.identity import IdentityContext


ENV_IDENTIFIER = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
VAULT_IDENTIFIER = re.compile(
    r"^(?P<mount>[a-z0-9][a-z0-9_-]{1,63})/"
    r"(?P<path>[A-Za-z0-9][A-Za-z0-9_./-]{0,255})#"
    r"(?P<field>[A-Za-z][A-Za-z0-9_-]{0,63})"
    r"(?:@(?P<version>[1-9][0-9]*))?$"
)
FORBIDDEN_METADATA_KEYS = re.compile(r"(?i)(secret|password|token|api[_-]?key|connection_string)")


class SecretResolutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SecretProvider(Protocol):
    provider_code: str

    def resolve(self, identifier: str) -> str: ...


class EnvironmentSecretProvider:
    provider_code = "ENV"

    def __init__(self, allowed_identifiers: set[str] | None = None) -> None:
        self.allowed_identifiers = allowed_identifiers or get_settings().secret_env_allowlist_set

    def resolve(self, identifier: str) -> str:
        if not ENV_IDENTIFIER.fullmatch(identifier) or identifier not in self.allowed_identifiers:
            raise SecretResolutionError("SECRET_IDENTIFIER_NOT_ALLOWED", "Secret identifier 未在显式允许列表中")
        value = os.environ.get(identifier)
        if not value:
            raise SecretResolutionError("SECRET_PROVIDER_VALUE_MISSING", "受控 Secret Provider 未返回值")
        return value


class VaultKVv2SecretProvider:
    provider_code = "VAULT_KV_V2"

    def __init__(
        self,
        *,
        address: str | None = None,
        role_id_file: str | None = None,
        secret_id_file: str | None = None,
        timeout_seconds: float | None = None,
        cache_ttl_seconds: int | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        settings = get_settings()
        self.address = (address or settings.vault_address).rstrip("/")
        self.role_id_file = Path(role_id_file or settings.vault_role_id_file)
        self.secret_id_file = Path(secret_id_file or settings.vault_secret_id_file)
        self.timeout_seconds = timeout_seconds or settings.vault_timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds or settings.vault_cache_ttl_seconds
        self.client = client or httpx.Client(timeout=self.timeout_seconds)
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def resolve(self, identifier: str) -> str:
        parsed = self.validate_identifier(identifier)
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(identifier)
            if cached and cached[1] > now:
                return cached[0]
        token = self._client_token()
        params = {"version": parsed["version"]} if parsed["version"] else None
        endpoint = (
            f"{self.address}/v1/{quote(parsed['mount'], safe='')}/data/"
            f"{quote(parsed['path'], safe='/')}"
        )
        try:
            response = self.client.get(endpoint, params=params, headers={"X-Vault-Token": token})
            if response.status_code == 403:
                self.invalidate_auth()
                response = self.client.get(
                    endpoint,
                    params=params,
                    headers={"X-Vault-Token": self._client_token()},
                )
            response.raise_for_status()
            payload = response.json()
            value = payload["data"]["data"][parsed["field"]]
            if not isinstance(value, str) or not value:
                raise KeyError(parsed["field"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise SecretResolutionError("VAULT_SECRET_UNAVAILABLE", "Vault 未返回可用 Secret") from exc
        with self._lock:
            self._cache[identifier] = (value, now + self.cache_ttl_seconds)
        return value

    @staticmethod
    def validate_identifier(identifier: str) -> dict[str, str | None]:
        match = VAULT_IDENTIFIER.fullmatch(identifier)
        if not match or ".." in identifier:
            raise SecretResolutionError("VAULT_IDENTIFIER_INVALID", "Vault Secret identifier 格式不合法")
        return match.groupdict()

    def invalidate(self, identifier: str | None = None) -> None:
        with self._lock:
            if identifier is None:
                self._cache.clear()
            else:
                self._cache.pop(identifier, None)

    def invalidate_auth(self) -> None:
        with self._lock:
            self._token = None
            self._token_expires_at = 0.0

    def health(self) -> bool:
        try:
            response = self.client.get(f"{self.address}/v1/sys/health")
            return response.status_code in {200, 429, 472, 473}
        except httpx.HTTPError:
            return False

    def _client_token(self) -> str:
        now = time.monotonic()
        with self._lock:
            if self._token and self._token_expires_at > now + 5:
                return self._token
        try:
            role_id = self.role_id_file.read_text(encoding="utf-8").strip()
            secret_id = self.secret_id_file.read_text(encoding="utf-8").strip()
            if not role_id or not secret_id:
                raise OSError("empty AppRole credential")
            response = self.client.post(
                f"{self.address}/v1/auth/approle/login",
                json={"role_id": role_id, "secret_id": secret_id},
            )
            response.raise_for_status()
            auth = response.json()["auth"]
            token = str(auth["client_token"])
            lease = max(30, int(auth.get("lease_duration") or 300))
        except (OSError, httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise SecretResolutionError("VAULT_AUTH_FAILED", "Vault AppRole 认证失败") from exc
        with self._lock:
            self._token = token
            self._token_expires_at = now + lease
        return token


class SecretProviderRegistry:
    def __init__(self, providers: tuple[SecretProvider, ...] | None = None) -> None:
        if providers is None:
            entries: tuple[SecretProvider, ...] = (EnvironmentSecretProvider(),)
            if get_settings().vault_enabled:
                entries = (*entries, VaultKVv2SecretProvider())
        else:
            entries = providers
        self.providers = {provider.provider_code: provider for provider in entries}

    def get(self, code: str) -> SecretProvider:
        provider = self.providers.get(code)
        if provider is None:
            raise SecretResolutionError("SECRET_PROVIDER_NOT_CONFIGURED", "Secret Provider 未配置")
        return provider


class CredentialReferenceService:
    def __init__(
        self,
        db: Session,
        identity: IdentityContext,
        *,
        providers: SecretProviderRegistry | None = None,
    ) -> None:
        self.db = db
        self.identity = identity
        self.providers = providers or SecretProviderRegistry()

    def create(
        self,
        *,
        reference_name: str,
        provider: str,
        secret_identifier: str,
        purpose: str,
        scenario_id: str | None,
        environment: str,
        allowed_actions: list[str],
        metadata: dict,
    ) -> CredentialReference:
        self._authorize("credential.manage", resource_id=reference_name, scenario_id=scenario_id)
        if provider == "ENV" and not ENV_IDENTIFIER.fullmatch(secret_identifier):
            raise SecretResolutionError("SECRET_IDENTIFIER_INVALID", "ENV identifier 格式不合法")
        if provider == "VAULT_KV_V2":
            VaultKVv2SecretProvider.validate_identifier(secret_identifier)
        if provider not in self.providers.providers:
            raise SecretResolutionError("SECRET_PROVIDER_NOT_CONFIGURED", "Secret Provider 未配置")
        if any(FORBIDDEN_METADATA_KEYS.search(str(key)) for key in metadata):
            raise SecretResolutionError("PLAINTEXT_SECRET_METADATA_REJECTED", "CredentialReference 元数据禁止保存敏感值")
        current_version = int(self.db.scalar(select(func.max(CredentialReference.version)).where(
            CredentialReference.tenant_id == self.identity.tenant_id,
            CredentialReference.workspace_id == self.identity.workspace_id,
            CredentialReference.reference_name == reference_name,
        )) or 0)
        record = CredentialReference(
            credential_ref_id=f"CRED-{uuid4()}",
            reference_name=reference_name,
            provider=provider,
            secret_identifier=secret_identifier,
            purpose=purpose,
            tenant_id=self.identity.tenant_id,
            workspace_id=self.identity.workspace_id,
            scenario_id=scenario_id,
            environment=environment,
            status=CredentialStatus.ACTIVE,
            version=current_version + 1,
            allowed_actions_json=json.dumps(sorted(set(allowed_actions)), sort_keys=True),
            metadata_json=json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            created_by=self.identity.subject_id,
        )
        self.db.add(record)
        record_governance_event(
            self.db, self.identity,
            action="credential.reference_created",
            resource_type="credential_reference",
            resource_id=record.credential_ref_id,
            result="SUCCESS",
            detail={"provider": provider, "purpose": purpose, "version": record.version},
        )
        self.db.commit()
        return record

    def rotate(self, credential_ref_id: str, *, secret_identifier: str, metadata: dict | None = None) -> CredentialReference:
        current = self._owned(credential_ref_id)
        self._authorize("credential.manage", resource_id=credential_ref_id, scenario_id=current.scenario_id)
        if current.status != CredentialStatus.ACTIVE:
            raise SecretResolutionError("CREDENTIAL_REFERENCE_NOT_ACTIVE", "只有 ACTIVE 引用可以轮换")
        replacement = self.create(
            reference_name=current.reference_name,
            provider=current.provider,
            secret_identifier=secret_identifier,
            purpose=current.purpose,
            scenario_id=current.scenario_id,
            environment=current.environment,
            allowed_actions=list(json.loads(current.allowed_actions_json)),
            metadata=metadata or json.loads(current.metadata_json),
        )
        current.status = CredentialStatus.SUPERSEDED
        current.updated_at = datetime.now(UTC)
        replacement.rotated_from_id = current.credential_ref_id
        invalidator = getattr(self.providers.get(current.provider), "invalidate", None)
        if invalidator:
            invalidator(current.secret_identifier)
        record_governance_event(
            self.db, self.identity,
            action="credential.reference_rotated",
            resource_type="credential_reference",
            resource_id=replacement.credential_ref_id,
            result="SUCCESS",
            detail={"previous_ref_id": current.credential_ref_id, "version": replacement.version},
        )
        self.db.commit()
        return replacement

    def set_status(self, credential_ref_id: str, status: CredentialStatus) -> CredentialReference:
        if status not in {CredentialStatus.DISABLED, CredentialStatus.REVOKED}:
            raise SecretResolutionError("CREDENTIAL_STATUS_INVALID", "只允许禁用或撤回引用")
        record = self._owned(credential_ref_id)
        self._authorize("credential.manage", resource_id=credential_ref_id, scenario_id=record.scenario_id)
        record.status = status
        now = datetime.now(UTC)
        record.updated_at = now
        if status is CredentialStatus.DISABLED:
            record.disabled_at = now
        else:
            record.revoked_at = now
        record_governance_event(
            self.db, self.identity,
            action=f"credential.reference_{status.lower()}",
            resource_type="credential_reference",
            resource_id=record.credential_ref_id,
            result="SUCCESS",
        )
        self.db.commit()
        return record

    def resolve(self, credential_ref_id: str, *, action: str, trace_id: str) -> SecretValue:
        record = self._owned(credential_ref_id)
        self._authorize("credential.use", resource_id=credential_ref_id, scenario_id=record.scenario_id, trace_id=trace_id)
        if record.status != CredentialStatus.ACTIVE:
            return self._usage_failure(record, action, trace_id, "CREDENTIAL_REFERENCE_DISABLED")
        allowed_actions = list(json.loads(record.allowed_actions_json))
        if "*" not in allowed_actions and action not in allowed_actions:
            return self._usage_failure(record, action, trace_id, "CREDENTIAL_ACTION_NOT_ALLOWED")
        try:
            value = self.providers.get(record.provider).resolve(record.secret_identifier)
        except SecretResolutionError as exc:
            self._audit_usage(record, action, "FAILED", trace_id, exc.code)
            record_governance_event(
                self.db, self.identity,
                action="credential.use_failed",
                resource_type="credential_reference",
                resource_id=record.credential_ref_id,
                result="FAILED",
                trace_id=trace_id,
                detail={"error_code": exc.code},
            )
            self.db.commit()
            raise
        self._audit_usage(record, action, "SUCCESS", trace_id, None)
        record_governance_event(
            self.db, self.identity,
            action="credential.use",
            resource_type="credential_reference",
            resource_id=record.credential_ref_id,
            result="SUCCESS",
            trace_id=trace_id,
            detail={"provider": record.provider, "purpose": record.purpose, "version": record.version},
        )
        self.db.commit()
        return SecretValue(value=value, credential_ref_id=record.credential_ref_id, version=record.version)

    def active_by_name(self, reference_name: str) -> CredentialReference:
        record = self.db.scalar(select(CredentialReference).where(
            CredentialReference.tenant_id == self.identity.tenant_id,
            CredentialReference.workspace_id == self.identity.workspace_id,
            CredentialReference.reference_name == reference_name,
            CredentialReference.status == CredentialStatus.ACTIVE,
        ).order_by(CredentialReference.version.desc()))
        if record is None:
            raise SecretResolutionError("CREDENTIAL_REFERENCE_NOT_FOUND", "CredentialReference 不存在或不可访问")
        return record

    def _usage_failure(self, record: CredentialReference, action: str, trace_id: str, code: str):
        self._audit_usage(record, action, "FAILED", trace_id, code)
        record_governance_event(
            self.db, self.identity,
            action="credential.use_failed",
            resource_type="credential_reference",
            resource_id=record.credential_ref_id,
            result="FAILED",
            trace_id=trace_id,
            detail={"error_code": code},
        )
        self.db.commit()
        raise SecretResolutionError(code, "CredentialReference 不可用")

    def _audit_usage(self, record: CredentialReference, action: str, outcome: str, trace_id: str, error_code: str | None) -> None:
        self.db.add(CredentialUsageAudit(
            usage_id=f"CREDUSE-{uuid4()}",
            credential_ref_id=record.credential_ref_id,
            tenant_id=self.identity.tenant_id,
            workspace_id=self.identity.workspace_id,
            actor_subject_id=self.identity.subject_id,
            action=action,
            outcome=outcome,
            error_code=error_code,
            trace_id=trace_id,
        ))
    def _owned(self, credential_ref_id: str) -> CredentialReference:
        record = self.db.get(CredentialReference, credential_ref_id)
        if record is None or record.tenant_id != self.identity.tenant_id or record.workspace_id != self.identity.workspace_id:
            raise SecretResolutionError("CREDENTIAL_REFERENCE_NOT_FOUND", "CredentialReference 不存在或不可访问")
        return record

    def _authorize(self, action: str, *, resource_id: str, scenario_id: str | None, trace_id: str | None = None) -> None:
        AuthorizationService(self.db, self.identity).require(request_context(
            self.identity,
            action=action,
            resource_type="credential_reference",
            resource_id=resource_id,
            scenario_id=scenario_id,
            environment=get_settings().app_env,
            trace_id=trace_id,
        ))
