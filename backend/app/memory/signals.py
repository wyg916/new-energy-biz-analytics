from __future__ import annotations

from datetime import UTC, datetime

from app.memory.contracts import MemoryStatus
from app.memory.models import MemoryRecord


def apply_recall_signal(record: MemoryRecord, *, now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    record.recall_count = int(record.recall_count or 0) + 1
    record.last_recalled_at = current
    if record.status == MemoryStatus.REDUCED_RANK:
        record.status = MemoryStatus.ACTIVE
        record.importance = min(round(record.importance + 0.05, 6), 1.0)
        record.lifecycle_transition_at = current
