from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import inspect, or_, select
from sqlalchemy.orm import Session

from app.memory.audit import audit_memory_use
from app.memory.authorization import MemoryAuthorization
from app.memory.contracts import MemoryStatus, MemoryType
from app.memory.models import MemoryRecord
from app.platform.identity import IdentityContext


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


@dataclass(frozen=True)
class LifecycleResult:
    expired: int
    archived: int
    decayed: int
    reduced_rank: int = 0
    cold: int = 0
    no_recall_ids: tuple[str, ...] = ()


class MemoryLifecycleService:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def maintain(
        self,
        *,
        scenario_id: str,
        now: datetime | None = None,
        system_scope: bool = False,
    ) -> LifecycleResult:
        current = now or datetime.now(UTC)
        if system_scope and not (
            self.identity.subject_id.startswith("system:")
            and "analyst_admin" in self.identity.roles
        ):
            raise PermissionError("SYSTEM_LIFECYCLE_SCOPE_FORBIDDEN")
        scope_filter = (
            (
                MemoryRecord.tenant_id == self.identity.tenant_id,
                MemoryRecord.organization_id == self.identity.org_id,
                MemoryRecord.workspace_id == self.identity.workspace_id,
                (
                    or_(MemoryRecord.scenario_id == scenario_id, MemoryRecord.scenario_id.is_(None))
                    if scenario_id == "charging_ops"
                    else MemoryRecord.scenario_id == scenario_id
                ),
            )
            if system_scope
            else (MemoryAuthorization.retrieval_filter(self.identity, scenario_id=scenario_id),)
        )
        records = self.db.scalars(select(MemoryRecord).where(
            *scope_filter,
            MemoryRecord.status.in_((MemoryStatus.ACTIVE, MemoryStatus.REDUCED_RANK, MemoryStatus.COLD, MemoryStatus.ARCHIVED)),
            MemoryRecord.deleted_at.is_(None),
        )).all()
        holds = []
        if inspect(self.db.get_bind()).has_table("legal_hold"):
            from app.governance.contracts import HoldStatus
            from app.governance.models import LegalHold

            holds = self.db.scalars(select(LegalHold).where(
                LegalHold.tenant_id == self.identity.tenant_id,
                LegalHold.workspace_id == self.identity.workspace_id,
                LegalHold.status == HoldStatus.ACTIVE,
                or_(LegalHold.resource_type == "memory", LegalHold.resource_type == "*"),
            )).all()
        expired = archived = decayed = reduced_rank = cold = 0
        no_recall_ids: list[str] = []
        for record in records:
            governed_hold = any(
                (hold.resource_id is None or hold.resource_id == record.memory_id)
                and (hold.user_id is None or hold.user_id == record.user_id)
                and (hold.memory_type is None or hold.memory_type == record.memory_type)
                for hold in holds
            )
            if record.legal_hold or governed_hold:
                continue
            if record.expires_at and _aware(record.expires_at) <= current:
                target_status = (
                    MemoryStatus.ARCHIVED
                    if record.memory_type == MemoryType.EPISODIC
                    else MemoryStatus.REVOKED
                )
                if record.status == target_status:
                    continue
                record.status = target_status
                if target_status == MemoryStatus.ARCHIVED:
                    archived += 1
                else:
                    expired += 1
                record.valid_to = current
                record.updated_at = current
                record.lifecycle_transition_at = current
                no_recall_ids.append(record.memory_id)
                continue
            signal_at = record.last_recalled_at or record.updated_at
            age_days = max((_aware(current) - _aware(signal_at)).days, 0)
            if age_days >= 90 and record.memory_type in {
                MemoryType.SEMANTIC,
                MemoryType.EPISODIC,
            }:
                if record.status != MemoryStatus.COLD:
                    record.status = MemoryStatus.COLD
                    record.valid_to = current
                    record.lifecycle_transition_at = current
                    record.updated_at = current
                    cold += 1
                    no_recall_ids.append(record.memory_id)
                continue
            if age_days >= 30 and record.memory_type in {
                MemoryType.SEMANTIC,
                MemoryType.EPISODIC,
            }:
                new_importance = max(round(record.importance * 0.95, 6), 0.05)
                if new_importance != record.importance:
                    record.importance = new_importance
                    record.updated_at = current
                    decayed += 1
                if record.status == MemoryStatus.ACTIVE:
                    record.status = MemoryStatus.REDUCED_RANK
                    record.lifecycle_transition_at = current
                    reduced_rank += 1
        audit_memory_use(
            self.db,
            self.identity,
            action="memory.lifecycle.maintain",
            outcome="success",
            detail={
                "expired": expired,
                "archived": archived,
                "decayed": decayed,
                "reduced_rank": reduced_rank,
                "cold": cold,
            },
        )
        self.db.commit()
        return LifecycleResult(
            expired=expired,
            archived=archived,
            decayed=decayed,
            reduced_rank=reduced_rank,
            cold=cold,
            no_recall_ids=tuple(no_recall_ids),
        )
