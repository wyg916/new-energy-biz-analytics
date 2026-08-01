from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class GovernanceStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DISABLED = "DISABLED"
    ROLLED_BACK = "ROLLED_BACK"


class CredentialStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class HoldStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


@dataclass(frozen=True)
class AuthorizationContext:
    action: str
    resource_type: str
    tenant_id: str
    workspace_id: str
    scenario_id: str | None = None
    resource_id: str | None = None
    owner_subject_id: str | None = None
    data_classification: str = "simulated"
    environment: str = "development"
    attributes: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    code: str
    reason: str
    permission: str
    matched_role_ids: tuple[str, ...] = ()
    matched_policy_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class OIDCClaims:
    issuer: str
    subject: str
    tenant_hint: str | None
    email: str | None
    display_name: str
    groups: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SecretValue:
    value: str
    credential_ref_id: str
    version: int
