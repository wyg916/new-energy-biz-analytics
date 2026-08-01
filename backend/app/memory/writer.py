from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.audit import audit_memory_use
from app.memory.authorization import MemoryAuthorization
from app.memory.conflict import MemoryConflictDetector
from app.memory.contracts import MemoryScope, MemoryStatus, MemoryType, TrustLevel
from app.memory.models import MemoryWriteCandidateRecord
from app.platform.identity import IdentityContext


SECRET_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|password|passwd|secret|token|credential|database[_-]?url|connection[_-]?string)",
    re.IGNORECASE,
)
BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"(?<![\w.-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")


class MemoryWriteError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MemoryWriteCandidate:
    memory_type: MemoryType
    scope_type: MemoryScope
    scenario_id: str | None
    content: str
    structured_value: dict[str, Any]
    source_type: str
    source_id: str | None
    trust_level: TrustLevel
    confidence: float
    importance: float
    approval_required: bool
    retention_policy: str
    write_reason: str
    idempotency_key: str
    data_classification: str = "internal"
    agent_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None


def _secret_path(value: Any, path: str = "") -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            child = f"{path}.{key}" if path else str(key)
            if SECRET_KEY_PATTERN.search(str(key)):
                return child
            found = _secret_path(nested, child)
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _secret_path(nested, f"{path}[{index}]")
            if found:
                return found
    elif isinstance(value, str) and BEARER_PATTERN.search(value):
        return path or "content"
    return None


def redact_text(value: str) -> str:
    return EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)


class MemoryWritePipeline:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def submit(self, candidate: MemoryWriteCandidate) -> MemoryWriteCandidateRecord:
        if candidate.memory_type is MemoryType.WORKING:
            raise MemoryWriteError(
                "WORKING_MEMORY_REDIS_ONLY",
                "Working Memory 只能写入带 TTL 的 Redis 状态",
            )
        if candidate.memory_type is MemoryType.PROCEDURAL and not candidate.approval_required:
            raise MemoryWriteError(
                "PROCEDURAL_APPROVAL_REQUIRED",
                "程序性记忆必须经过人工审核",
            )
        if candidate.memory_type is MemoryType.SEMANTIC and (
            candidate.trust_level is TrustLevel.UNVERIFIED and not candidate.approval_required
        ):
            raise MemoryWriteError(
                "SEMANTIC_CONFIRMATION_REQUIRED",
                "未经确认的语义记忆不能直接生效",
            )
        if "SQLBOT_SHADOW" in candidate.source_type.upper() and candidate.memory_type in {
            MemoryType.SEMANTIC,
            MemoryType.EPISODIC,
        }:
            raise MemoryWriteError(
                "SQLBOT_SHADOW_FACT_FORBIDDEN",
                "SQLBot Shadow 只能写入评测证据",
            )
        secret_path = _secret_path(
            {"content": candidate.content, "structured_value": candidate.structured_value}
        )
        if secret_path:
            audit_memory_use(
                self.db,
                self.identity,
                action="memory.write.submit",
                outcome="rejected",
                run_id=candidate.run_id,
                reason="SECRET_FIELD_REJECTED",
                detail={"field_path": secret_path},
                commit=True,
            )
            raise MemoryWriteError("SECRET_FIELD_REJECTED", "记忆候选包含密钥或凭据")
        existing = self.db.scalar(select(MemoryWriteCandidateRecord).where(
            MemoryWriteCandidateRecord.idempotency_key == candidate.idempotency_key
        ))
        if existing:
            return existing
        scope = MemoryAuthorization.scope_from_identity(
            self.identity,
            candidate.scope_type,
            scenario_id=candidate.scenario_id,
            agent_id=candidate.agent_id,
            session_id=candidate.session_id,
            run_id=candidate.run_id,
        )
        content = redact_text(candidate.content.strip())
        structured = json.loads(
            EMAIL_PATTERN.sub(
                "[REDACTED_EMAIL]",
                json.dumps(candidate.structured_value, ensure_ascii=False, sort_keys=True),
            )
        )
        structured_json = json.dumps(structured, ensure_ascii=False, sort_keys=True)
        logical_key = structured.get("key") or structured.get("procedure_code") or content
        duplicate_hash = hashlib.sha256(
            "|".join(
                (
                    scope.tenant_id,
                    scope.workspace_id,
                    scope.user_id or "*",
                    scope.scenario_id or "*",
                    candidate.memory_type,
                    str(logical_key),
                )
            ).encode("utf-8")
        ).hexdigest()
        conflict = MemoryConflictDetector(self.db).detect(
            duplicate_hash=duplicate_hash,
            structured_value_json=structured_json,
        )
        record = MemoryWriteCandidateRecord(
            candidate_id=f"MEMC-{uuid4()}",
            memory_type=candidate.memory_type,
            scope_type=scope.scope_type,
            tenant_id=scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            user_id=scope.user_id,
            agent_id=scope.agent_id,
            session_id=scope.session_id,
            run_id=scope.run_id,
            scenario_id=scope.scenario_id,
            content=content,
            structured_value_json=structured_json,
            source_type=candidate.source_type,
            source_id=candidate.source_id,
            trust_level=candidate.trust_level,
            confidence=min(max(candidate.confidence, 0.0), 1.0),
            importance=min(max(candidate.importance, 0.0), 1.0),
            duplicate_hash=duplicate_hash,
            conflict_group=conflict.conflict_group,
            data_classification=candidate.data_classification,
            approval_required=candidate.approval_required,
            retention_policy=candidate.retention_policy,
            write_reason=candidate.write_reason[:256],
            rejection_reason=(
                "DUPLICATE_ACTIVE_MEMORY" if conflict.duplicate_memory_id else None
            ),
            status=(
                MemoryStatus.REJECTED
                if conflict.duplicate_memory_id
                else MemoryStatus.CANDIDATE
            ),
            idempotency_key=candidate.idempotency_key,
        )
        self.db.add(record)
        audit_memory_use(
            self.db,
            self.identity,
            action="memory.write.submit",
            outcome=("duplicate" if conflict.duplicate_memory_id else "candidate"),
            candidate_id=record.candidate_id,
            run_id=candidate.run_id,
            detail={
                "memory_type": candidate.memory_type,
                "scope_type": candidate.scope_type,
                "conflict_group": conflict.conflict_group,
                "duplicate_memory_id": conflict.duplicate_memory_id,
            },
        )
        self.db.commit()
        return record
