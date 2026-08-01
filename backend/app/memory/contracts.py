from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class MemoryType(StrEnum):
    WORKING = "WORKING"
    SEMANTIC = "SEMANTIC"
    EPISODIC = "EPISODIC"
    PROCEDURAL = "PROCEDURAL"
    GOVERNANCE = "GOVERNANCE"


class MemoryScope(StrEnum):
    GLOBAL = "GLOBAL"
    TENANT = "TENANT"
    WORKSPACE = "WORKSPACE"
    USER = "USER"
    AGENT = "AGENT"
    SESSION = "SESSION"
    RUN = "RUN"


class MemoryStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"
    REVOKED = "REVOKED"
    DELETED = "DELETED"


class TrustLevel(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    USER_CONFIRMED = "USER_CONFIRMED"
    SYSTEM_VERIFIED = "SYSTEM_VERIFIED"
    APPROVED_POLICY = "APPROVED_POLICY"


class ProcedureStatus(StrEnum):
    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    REVIEWING = "REVIEWING"
    APPROVED = "APPROVED"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ScopeContext:
    scope_type: MemoryScope
    tenant_id: str
    organization_id: str
    workspace_id: str
    user_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    scenario_id: str | None = None


@dataclass(frozen=True)
class ContextSections:
    system_constraints: tuple[str, ...] = ()
    identity_and_permissions: dict[str, Any] = field(default_factory=dict)
    active_procedure: dict[str, Any] | None = None
    semantic_facts: tuple[dict[str, Any], ...] = ()
    episodic_examples: tuple[dict[str, Any], ...] = ()
    working_state: dict[str, Any] = field(default_factory=dict)
    current_data: dict[str, Any] = field(default_factory=dict)
    rag_evidence: tuple[dict[str, Any], ...] = ()
    user_question: str = ""


@dataclass(frozen=True)
class MemoryView:
    memory_id: str
    memory_type: MemoryType
    scope_type: MemoryScope
    scenario_id: str | None
    content: str
    structured_value: dict[str, Any]
    trust_level: TrustLevel
    confidence: float
    importance: float
    status: MemoryStatus
    version: int
    expires_at: datetime | None
    source_type: str
    source_id: str | None
