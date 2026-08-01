from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.audit import audit_memory_use
from app.memory.authorization import MemoryAuthorization
from app.memory.contracts import MemoryScope, MemoryStatus, MemoryType, TrustLevel
from app.memory.models import MemoryRecord, MemoryWriteCandidateRecord
from app.platform.identity import IdentityContext


ALLOWED_SEMANTIC_KEYS = {
    "answer_style",
    "default_scenario",
    "default_time_range",
    "default_region",
    "frequent_metrics",
    "confirmed_preference",
    "corrected_term",
    "tenant_analysis_config_ref",
    "memory_enabled",
}
FORBIDDEN_SEMANTIC_KEYS = {
    "revenue",
    "order_amount",
    "root_cause",
    "sqlbot_shadow",
    "metric_definition",
    "password",
    "token",
    "credential",
}


class SemanticMemoryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def semantic_duplicate_hash(identity: IdentityContext, key: str, scenario_id: str | None) -> str:
    raw = "|".join(
        (
            identity.tenant_id,
            identity.workspace_id,
            identity.subject_id,
            scenario_id or "*",
            key,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SemanticMemoryService:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def propose(
        self,
        *,
        key: str,
        value,
        scenario_id: str | None,
        source_type: str,
        source_id: str | None,
        explicitly_confirmed: bool,
        idempotency_key: str,
        write_reason: str,
    ) -> MemoryWriteCandidateRecord:
        normalized_key = key.strip().lower()
        if normalized_key in FORBIDDEN_SEMANTIC_KEYS or normalized_key not in ALLOWED_SEMANTIC_KEYS:
            raise SemanticMemoryError("SEMANTIC_CONTENT_FORBIDDEN", "该内容不允许保存为语义记忆")
        existing = self.db.scalar(select(MemoryWriteCandidateRecord).where(
            MemoryWriteCandidateRecord.idempotency_key == idempotency_key
        ))
        if existing:
            return existing
        scope = MemoryAuthorization.scope_from_identity(
            self.identity,
            MemoryScope.USER,
            scenario_id=scenario_id,
        )
        candidate = MemoryWriteCandidateRecord(
            candidate_id=f"MEMC-{uuid4()}",
            memory_type=MemoryType.SEMANTIC,
            scope_type=scope.scope_type,
            tenant_id=scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            user_id=scope.user_id,
            scenario_id=scope.scenario_id,
            content=f"{normalized_key}={value}",
            structured_value_json=json.dumps(
                {"key": normalized_key, "value": value}, ensure_ascii=False, sort_keys=True
            ),
            source_type=source_type,
            source_id=source_id,
            trust_level=(
                TrustLevel.USER_CONFIRMED if explicitly_confirmed else TrustLevel.UNVERIFIED
            ),
            confidence=1.0 if explicitly_confirmed else 0.5,
            importance=0.6,
            duplicate_hash=semantic_duplicate_hash(self.identity, normalized_key, scenario_id),
            data_classification="internal",
            approval_required=not explicitly_confirmed,
            retention_policy="USER_PREFERENCE",
            write_reason=write_reason,
            status=(MemoryStatus.PENDING_APPROVAL if not explicitly_confirmed else MemoryStatus.CANDIDATE),
            idempotency_key=idempotency_key,
        )
        self.db.add(candidate)
        audit_memory_use(
            self.db,
            self.identity,
            action="semantic.propose",
            outcome="candidate",
            candidate_id=candidate.candidate_id,
            detail={"key": normalized_key, "confirmed": explicitly_confirmed},
        )
        self.db.commit()
        return candidate

    def confirm(self, candidate_id: str) -> MemoryRecord:
        candidate = self.db.get(MemoryWriteCandidateRecord, candidate_id)
        if candidate is None:
            raise SemanticMemoryError("MEMORY_CANDIDATE_NOT_FOUND", "记忆候选不存在")
        if candidate.memory_type != MemoryType.SEMANTIC:
            raise SemanticMemoryError("MEMORY_TYPE_MISMATCH", "候选不是语义记忆")
        if candidate.tenant_id != self.identity.tenant_id or candidate.workspace_id != self.identity.workspace_id or candidate.user_id != self.identity.subject_id:
            raise SemanticMemoryError("MEMORY_CANDIDATE_FORBIDDEN", "记忆候选不属于当前用户")
        existing = self.db.scalar(select(MemoryRecord).where(
            MemoryRecord.duplicate_hash == candidate.duplicate_hash,
            MemoryRecord.status == MemoryStatus.ACTIVE,
        ).order_by(MemoryRecord.version.desc()))
        if existing and existing.structured_value_json == candidate.structured_value_json:
            candidate.status = MemoryStatus.REJECTED
            candidate.rejection_reason = "DUPLICATE_ACTIVE_MEMORY"
            candidate.reviewed_by = self.identity.subject_id
            candidate.reviewed_at = datetime.now(UTC)
            audit_memory_use(
                self.db,
                self.identity,
                action="semantic.confirm",
                outcome="duplicate",
                memory_id=existing.memory_id,
                candidate_id=candidate.candidate_id,
            )
            self.db.commit()
            return existing
        version = (existing.version + 1) if existing else 1
        conflict_group = f"MEMCON-{uuid4()}" if existing else None
        if existing:
            existing.status = MemoryStatus.SUPERSEDED
            existing.valid_to = datetime.now(UTC)
            existing.conflict_group = existing.conflict_group or conflict_group
            existing.updated_at = datetime.now(UTC)
        record = MemoryRecord(
            memory_id=f"MEM-{uuid4()}",
            memory_type=MemoryType.SEMANTIC,
            scope_type=candidate.scope_type,
            tenant_id=candidate.tenant_id,
            organization_id=candidate.organization_id,
            workspace_id=candidate.workspace_id,
            user_id=candidate.user_id,
            scenario_id=candidate.scenario_id,
            content=candidate.content,
            structured_value_json=candidate.structured_value_json,
            source_type=candidate.source_type,
            source_id=candidate.source_id,
            trust_level=TrustLevel.USER_CONFIRMED,
            confidence=1.0,
            importance=candidate.importance,
            status=MemoryStatus.ACTIVE,
            version=version,
            duplicate_hash=candidate.duplicate_hash,
            conflict_group=conflict_group,
            retention_policy=candidate.retention_policy,
            approval_required=False,
        )
        candidate.status = MemoryStatus.ACTIVE
        candidate.trust_level = TrustLevel.USER_CONFIRMED
        candidate.reviewed_by = self.identity.subject_id
        candidate.reviewed_at = datetime.now(UTC)
        self.db.add(record)
        audit_memory_use(
            self.db,
            self.identity,
            action="semantic.confirm",
            outcome="success",
            memory_id=record.memory_id,
            candidate_id=candidate.candidate_id,
            detail={"version": version, "conflict_group": conflict_group},
        )
        self.db.commit()
        return record

    def reject(self, candidate_id: str, *, reason: str) -> None:
        candidate = self.db.get(MemoryWriteCandidateRecord, candidate_id)
        if candidate is None or candidate.user_id != self.identity.subject_id:
            raise SemanticMemoryError("MEMORY_CANDIDATE_NOT_FOUND", "记忆候选不存在")
        candidate.status = MemoryStatus.REJECTED
        candidate.rejection_reason = reason[:500]
        candidate.reviewed_by = self.identity.subject_id
        candidate.reviewed_at = datetime.now(UTC)
        audit_memory_use(
            self.db,
            self.identity,
            action="semantic.reject",
            outcome="success",
            candidate_id=candidate.candidate_id,
            reason=reason[:500],
        )
        self.db.commit()
