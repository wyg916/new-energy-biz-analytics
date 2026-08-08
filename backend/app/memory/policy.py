from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.authorization import MemoryAuthorization
from app.memory.contracts import MemoryStatus, MemoryType
from app.memory.models import MemoryRecord
from app.platform.identity import IdentityContext


class MemoryPolicyService:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def is_enabled(self, *, scenario_id: str) -> bool:
        records = self.db.scalars(select(MemoryRecord).where(
            MemoryAuthorization.retrieval_filter(self.identity, scenario_id=scenario_id),
            MemoryRecord.memory_type == MemoryType.SEMANTIC,
            MemoryRecord.status.in_((MemoryStatus.ACTIVE, MemoryStatus.REDUCED_RANK)),
            MemoryRecord.deleted_at.is_(None),
        ).order_by(MemoryRecord.version.desc())).all()
        for record in records:
            value = json.loads(record.structured_value_json)
            if value.get("key") == "memory_enabled":
                return bool(value.get("value"))
        return True
