from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.governance.audit import record_governance_event
from app.governance.authorization import AuthorizationService, request_context
from app.governance.contracts import HoldStatus
from app.governance.models import LegalHold, RetentionPolicy
from app.platform.identity import IdentityContext


class RetentionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DeletionGovernanceDecision:
    allowed: bool
    code: str
    legal_hold_id: str | None = None
    retention_policy_id: str | None = None


class LegalHoldService:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def create(
        self,
        *,
        resource_type: str,
        resource_id: str | None,
        user_id: str | None,
        memory_type: str | None,
        reason_code: str,
        reason: str,
    ) -> LegalHold:
        self._authorize("legal_hold.manage", resource_id=resource_id)
        hold = LegalHold(
            legal_hold_id=f"HOLD-{uuid4()}",
            tenant_id=self.identity.tenant_id,
            workspace_id=self.identity.workspace_id,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            memory_type=memory_type,
            reason_code=reason_code,
            reason=reason,
            status=HoldStatus.ACTIVE,
            created_by=self.identity.subject_id,
        )
        self.db.add(hold)
        record_governance_event(
            self.db, self.identity,
            action="legal_hold.created",
            resource_type=resource_type,
            resource_id=resource_id,
            result="SUCCESS",
            detail={"legal_hold_id": hold.legal_hold_id, "reason_code": reason_code},
        )
        self.db.commit()
        return hold

    def release(self, legal_hold_id: str, *, reason: str) -> LegalHold:
        self._authorize("legal_hold.manage", resource_id=legal_hold_id)
        hold = self.db.get(LegalHold, legal_hold_id)
        if hold is None or hold.tenant_id != self.identity.tenant_id or hold.workspace_id != self.identity.workspace_id:
            raise RetentionError("LEGAL_HOLD_NOT_FOUND", "Legal Hold 不存在")
        if hold.status != HoldStatus.ACTIVE:
            raise RetentionError("LEGAL_HOLD_NOT_ACTIVE", "Legal Hold 已解除")
        hold.status = HoldStatus.RELEASED
        hold.released_by = self.identity.subject_id
        hold.released_at = datetime.now(UTC)
        hold.release_reason = reason
        record_governance_event(
            self.db, self.identity,
            action="legal_hold.released",
            resource_type=hold.resource_type,
            resource_id=hold.resource_id,
            result="SUCCESS",
            detail={"legal_hold_id": hold.legal_hold_id},
        )
        self.db.commit()
        return hold

    def _authorize(self, action: str, *, resource_id: str | None) -> None:
        AuthorizationService(self.db, self.identity).require(request_context(
            self.identity,
            action=action,
            resource_type="legal_hold",
            resource_id=resource_id,
            environment=get_settings().app_env,
        ))


class RetentionPolicyService:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def create(
        self,
        *,
        policy_code: str,
        resource_type: str,
        resource_id: str | None,
        user_id: str | None,
        memory_type: str | None,
        retention_days: int,
        archive_after_days: int | None,
        deletion_mode: str,
    ) -> RetentionPolicy:
        AuthorizationService(self.db, self.identity).require(request_context(
            self.identity,
            action="retention.manage",
            resource_type="retention",
            resource_id=policy_code,
            environment=get_settings().app_env,
        ))
        versions = list(self.db.scalars(select(RetentionPolicy.version).where(
            RetentionPolicy.tenant_id == self.identity.tenant_id,
            RetentionPolicy.workspace_id == self.identity.workspace_id,
            RetentionPolicy.policy_code == policy_code,
        )).all())
        policy = RetentionPolicy(
            retention_policy_id=f"RET-{uuid4()}",
            policy_code=policy_code,
            version=max(versions, default=0) + 1,
            tenant_id=self.identity.tenant_id,
            workspace_id=self.identity.workspace_id,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            memory_type=memory_type,
            retention_days=retention_days,
            archive_after_days=archive_after_days,
            deletion_mode=deletion_mode,
            status="DRAFT",
            created_by=self.identity.subject_id,
        )
        self.db.add(policy)
        self.db.commit()
        return policy

    def approve_and_activate(self, retention_policy_id: str) -> RetentionPolicy:
        AuthorizationService(self.db, self.identity).require(request_context(
            self.identity,
            action="retention.manage",
            resource_type="retention",
            resource_id=retention_policy_id,
            environment=get_settings().app_env,
        ))
        policy = self.db.get(RetentionPolicy, retention_policy_id)
        if policy is None or policy.status != "DRAFT":
            raise RetentionError("RETENTION_POLICY_INVALID_STATE", "只有 DRAFT 策略可以批准")
        policy.status = "ACTIVE"
        policy.approved_by = self.identity.subject_id
        policy.approved_at = datetime.now(UTC)
        self.db.commit()
        return policy


class DeletionGovernance:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def evaluate(
        self,
        *,
        resource_type: str,
        resource_id: str,
        user_id: str | None,
        memory_type: str | None,
        created_at: datetime,
        trace_id: str | None = None,
    ) -> DeletionGovernanceDecision:
        holds = list(self.db.scalars(select(LegalHold).where(
            LegalHold.tenant_id == self.identity.tenant_id,
            LegalHold.workspace_id == self.identity.workspace_id,
            LegalHold.status == HoldStatus.ACTIVE,
            or_(LegalHold.resource_type == resource_type, LegalHold.resource_type == "*"),
            or_(LegalHold.resource_id.is_(None), LegalHold.resource_id == resource_id),
            or_(LegalHold.user_id.is_(None), LegalHold.user_id == user_id),
            or_(LegalHold.memory_type.is_(None), LegalHold.memory_type == memory_type),
        )).all())
        if holds:
            hold = holds[0]
            record_governance_event(
                self.db, self.identity,
                action="legal_hold.delete_blocked",
                resource_type=resource_type,
                resource_id=resource_id,
                result="BLOCKED",
                trace_id=trace_id,
                detail={"legal_hold_id": hold.legal_hold_id},
                commit=True,
            )
            return DeletionGovernanceDecision(False, "LEGAL_HOLD_BLOCKED", legal_hold_id=hold.legal_hold_id)
        policies = list(self.db.scalars(select(RetentionPolicy).where(
            RetentionPolicy.tenant_id == self.identity.tenant_id,
            RetentionPolicy.workspace_id == self.identity.workspace_id,
            RetentionPolicy.status == "ACTIVE",
            or_(RetentionPolicy.resource_type == resource_type, RetentionPolicy.resource_type == "*"),
            or_(RetentionPolicy.resource_id.is_(None), RetentionPolicy.resource_id == resource_id),
            or_(RetentionPolicy.user_id.is_(None), RetentionPolicy.user_id == user_id),
            or_(RetentionPolicy.memory_type.is_(None), RetentionPolicy.memory_type == memory_type),
        )).all())
        now = datetime.now(UTC)
        aware_created = created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at
        strictest = max(policies, key=lambda item: item.retention_days, default=None)
        if strictest and (now - aware_created).days < strictest.retention_days:
            record_governance_event(
                self.db, self.identity,
                action="retention.delete_blocked",
                resource_type=resource_type,
                resource_id=resource_id,
                result="BLOCKED",
                trace_id=trace_id,
                detail={"retention_policy_id": strictest.retention_policy_id},
                commit=True,
            )
            return DeletionGovernanceDecision(False, "RETENTION_POLICY_BLOCKED", retention_policy_id=strictest.retention_policy_id)
        return DeletionGovernanceDecision(True, "DELETE_ALLOWED")
