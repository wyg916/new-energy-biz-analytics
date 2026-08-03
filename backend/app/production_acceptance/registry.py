from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.governance.audit import record_governance_event
from app.governance.authorization import AuthorizationService, request_context
from app.platform.identity import IdentityContext
from app.production_acceptance.models import ProductionGate, ProductionGateHistory


GATE_STATUSES = {"OPEN", "IN_PROGRESS", "PASSED", "WAIVED", "BLOCKED", "EXPIRED"}
BLOCKING_LEVELS = {"BLOCKER", "MAJOR", "ADVISORY"}
PROHIBITED_APPROVER_VALUES = {"", "tbd", "unknown", "none", "n/a", "system", "auto"}
V4_EXCLUDED_GATE_CODES = {
    "SQLBOT_IMAGE_SECURITY",
    "SQLBOT_EXTERNAL_REVIEW",
    "SQLBOT_EXTERNAL_RUNTIME",
}


class ProductionGateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalized_evidence(evidence: list[dict]) -> tuple[str, str | None]:
    payload = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest() if evidence else None
    return payload, digest


class ProductionGateRegistry:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def list(self) -> list[ProductionGate]:
        self._authorize("production_gate.view")
        return list(self.db.scalars(select(ProductionGate).where(
            ProductionGate.tenant_id == self.identity.tenant_id,
            ProductionGate.workspace_id == self.identity.workspace_id,
            ProductionGate.environment == "production",
        ).order_by(ProductionGate.category, ProductionGate.gate_code)).all())

    def history(self, gate_code: str) -> list[ProductionGateHistory]:
        gate = self._owned(gate_code)
        self._authorize("production_gate.view", gate_id=gate.gate_id)
        return list(self.db.scalars(select(ProductionGateHistory).where(
            ProductionGateHistory.gate_id == gate.gate_id,
            ProductionGateHistory.tenant_id == self.identity.tenant_id,
            ProductionGateHistory.workspace_id == self.identity.workspace_id,
        ).order_by(desc(ProductionGateHistory.created_at))).all())

    def decide(
        self,
        gate_code: str,
        *,
        status: str,
        evidence: list[dict],
        expires_at: datetime,
        reason: str,
        waiver_approved_by: str | None = None,
        waiver_basis: str | None = None,
        waiver_evidence_hash: str | None = None,
    ) -> ProductionGate:
        gate = self._owned(gate_code)
        self._authorize("production_gate.manage", gate_id=gate.gate_id)
        if status not in GATE_STATUSES:
            raise ProductionGateError("PRODUCTION_GATE_STATUS_INVALID", "生产门禁状态不在允许集合中")
        expires_at = self._aware(expires_at)
        if expires_at <= datetime.now(UTC):
            raise ProductionGateError("PRODUCTION_GATE_EXPIRY_INVALID", "门禁复核到期时间必须在未来")
        evidence_json, evidence_hash = normalized_evidence(evidence)
        if status in {"PASSED", "WAIVED"} and not evidence:
            raise ProductionGateError("PRODUCTION_GATE_EVIDENCE_REQUIRED", "PASSED 或 WAIVED 必须包含实际证据")
        if status == "WAIVED":
            approver = (waiver_approved_by or "").strip()
            basis = (waiver_basis or "").strip()
            if approver.lower() in PROHIBITED_APPROVER_VALUES or len(approver) < 3:
                raise ProductionGateError("PRODUCTION_GATE_WAIVER_APPROVER_REQUIRED", "WAIVED 必须包含明确正式批准人")
            if len(basis) < 12 or not waiver_evidence_hash:
                raise ProductionGateError("PRODUCTION_GATE_WAIVER_BASIS_REQUIRED", "WAIVED 必须包含风险接受依据和证据哈希")
            approval_evidence = [
                item for item in evidence
                if item.get("evidence_type") == "approval"
                and str(item.get("uri", "")).startswith("approval://")
                and item.get("sha256") == waiver_evidence_hash
            ]
            if not approval_evidence:
                raise ProductionGateError(
                    "PRODUCTION_GATE_WAIVER_APPROVAL_EVIDENCE_REQUIRED",
                    "WAIVED 必须引用与风险接受哈希一致的正式 approval 证据",
                )
        else:
            waiver_approved_by = None
            waiver_basis = None
            waiver_evidence_hash = None

        now = datetime.now(UTC)
        previous_status = self.effective_status(gate, now=now)
        gate.status = status
        gate.evidence_json = evidence_json
        gate.evidence_hash = evidence_hash
        gate.expires_at = expires_at
        gate.last_verified_at = now if evidence else None
        gate.waiver_approved_by = waiver_approved_by
        gate.waiver_basis = waiver_basis
        gate.waiver_evidence_hash = waiver_evidence_hash
        gate.version += 1
        gate.updated_at = now
        history = ProductionGateHistory(
            history_id=f"GATEH-{uuid4()}",
            gate_id=gate.gate_id,
            gate_code=gate.gate_code,
            tenant_id=gate.tenant_id,
            workspace_id=gate.workspace_id,
            previous_status=previous_status,
            status=status,
            evidence_json=evidence_json,
            evidence_hash=evidence_hash,
            reason=reason,
            actor_subject_id=self.identity.subject_id,
            version=gate.version,
            created_at=now,
        )
        self.db.add(history)
        record_governance_event(
            self.db,
            self.identity,
            action="production_gate.decision_recorded",
            resource_type="production_gate",
            resource_id=gate.gate_id,
            result="SUCCESS",
            detail={
                "gate_code": gate.gate_code,
                "previous_status": previous_status,
                "status": status,
                "evidence_hash": evidence_hash,
                "version": gate.version,
                "waived": status == "WAIVED",
            },
        )
        self.db.commit()
        return gate

    def summary(self, gates: list[ProductionGate] | None = None) -> dict:
        rows = gates if gates is not None else self.list()
        statuses = {row.gate_code: self.effective_status(row) for row in rows}
        unresolved_blockers = [
            row.gate_code for row in rows
            if (
                row.blocker_level == "BLOCKER"
                and row.gate_code not in V4_EXCLUDED_GATE_CODES
                and statuses[row.gate_code] not in {"PASSED", "WAIVED"}
            )
        ]
        waived = [row.gate_code for row in rows if statuses[row.gate_code] == "WAIVED"]
        return {
            "counts": {status: sum(value == status for value in statuses.values()) for status in sorted(GATE_STATUSES)},
            "unresolved_blockers": sorted(unresolved_blockers),
            "waived_gates": sorted(waived),
            "not_applicable_to_v4": sorted(V4_EXCLUDED_GATE_CODES.intersection(statuses)),
            "production_acceptance_ready": not unresolved_blockers,
            "go_no_go_recommendation": "GO_REVIEW_REQUIRED" if not unresolved_blockers else "NO_GO",
            "production_release_authorized": False,
            "production_traffic_switched": False,
            "sqlbot_canary_eligible": False,
        }

    @staticmethod
    def release_scope(gate_code: str) -> dict[str, object]:
        excluded = gate_code in V4_EXCLUDED_GATE_CODES
        return {
            "applicable_to_release": not excluded,
            "blocking_scope": "future_sqlbot_release" if excluded else "current_release",
            "release_disposition": "DEFERRED" if excluded else "IN_SCOPE",
        }

    @staticmethod
    def effective_status(gate: ProductionGate, *, now: datetime | None = None) -> str:
        at = now or datetime.now(UTC)
        expires_at = ProductionGateRegistry._aware(gate.expires_at)
        if expires_at <= at and gate.status in {"PASSED", "WAIVED"}:
            return "EXPIRED"
        return gate.status

    def _owned(self, gate_code: str) -> ProductionGate:
        gate = self.db.scalar(select(ProductionGate).where(
            ProductionGate.tenant_id == self.identity.tenant_id,
            ProductionGate.workspace_id == self.identity.workspace_id,
            ProductionGate.environment == "production",
            ProductionGate.gate_code == gate_code,
        ))
        if gate is None:
            raise ProductionGateError("PRODUCTION_GATE_NOT_FOUND", "生产门禁不存在或不在当前可信作用域")
        return gate

    def _authorize(self, action: str, *, gate_id: str | None = None) -> None:
        AuthorizationService(self.db, self.identity).require(request_context(
            self.identity,
            action=action,
            resource_type="production_gate",
            resource_id=gate_id,
            environment=get_settings().app_env,
        ))

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
