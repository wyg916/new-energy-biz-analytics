from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.contracts import MemoryStatus
from app.memory.models import MemoryRecord


@dataclass(frozen=True)
class ConflictResult:
    conflict_group: str | None
    conflicting_memory_ids: tuple[str, ...]
    duplicate_memory_id: str | None = None


class MemoryConflictDetector:
    def __init__(self, db: Session) -> None:
        self.db = db

    def detect(
        self,
        *,
        duplicate_hash: str,
        structured_value_json: str,
    ) -> ConflictResult:
        active = self.db.scalars(select(MemoryRecord).where(
            MemoryRecord.duplicate_hash == duplicate_hash,
            MemoryRecord.status.in_((MemoryStatus.ACTIVE, MemoryStatus.REDUCED_RANK)),
            MemoryRecord.deleted_at.is_(None),
        ).order_by(MemoryRecord.version.desc())).all()
        if not active:
            return ConflictResult(None, ())
        normalized = json.dumps(json.loads(structured_value_json), ensure_ascii=False, sort_keys=True)
        for record in active:
            current = json.dumps(
                json.loads(record.structured_value_json), ensure_ascii=False, sort_keys=True
            )
            if current == normalized:
                return ConflictResult(
                    record.conflict_group,
                    tuple(item.memory_id for item in active),
                    duplicate_memory_id=record.memory_id,
                )
        conflict_group = next(
            (item.conflict_group for item in active if item.conflict_group),
            f"MEMCON-{uuid4()}",
        )
        return ConflictResult(
            conflict_group,
            tuple(item.memory_id for item in active),
        )
