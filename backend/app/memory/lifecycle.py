from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
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


class MemoryLifecycleService:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def maintain(self, *, scenario_id: str, now: datetime | None = None) -> LifecycleResult:
        current = now or datetime.now(UTC)
        records = self.db.scalars(select(MemoryRecord).where(
            MemoryAuthorization.retrieval_filter(self.identity, scenario_id=scenario_id),
            MemoryRecord.status.in_((MemoryStatus.ACTIVE, MemoryStatus.ARCHIVED)),
            MemoryRecord.deleted_at.is_(None),
        )).all()
        expired = archived = decayed = 0
        for record in records:
            if record.legal_hold:
                continue
            if record.expires_at and _aware(record.expires_at) <= current:
                if record.memory_type == MemoryType.EPISODIC:
                    record.status = MemoryStatus.ARCHIVED
                    archived += 1
                else:
                    record.status = MemoryStatus.REVOKED
                    expired += 1
                record.valid_to = current
                record.updated_at = current
                continue
            age_days = max((_aware(current) - _aware(record.updated_at)).days, 0)
            if age_days >= 30 and record.memory_type in {
                MemoryType.SEMANTIC,
                MemoryType.EPISODIC,
            }:
                new_importance = max(round(record.importance * 0.95, 6), 0.05)
                if new_importance != record.importance:
                    record.importance = new_importance
                    record.updated_at = current
                    decayed += 1
        audit_memory_use(
            self.db,
            self.identity,
            action="memory.lifecycle.maintain",
            outcome="success",
            detail={"expired": expired, "archived": archived, "decayed": decayed},
        )
        self.db.commit()
        return LifecycleResult(expired=expired, archived=archived, decayed=decayed)
