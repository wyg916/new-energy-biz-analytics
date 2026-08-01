from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.governance.audit import record_governance_event
from app.governance.authorization import AuthorizationService, request_context
from app.governance.contracts import CredentialStatus, SecretValue
from app.governance.models import CredentialReference, CredentialUsageAudit
from app.platform.identity import IdentityContext


ENV_IDENTIFIER = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
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


class SecretProviderRegistry:
    def __init__(self, providers: tuple[SecretProvider, ...] | None = None) -> None:
        entries = providers or (EnvironmentSecretProvider(),)
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
