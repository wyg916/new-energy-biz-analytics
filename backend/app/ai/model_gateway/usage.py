from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock


@dataclass(frozen=True)
class UsageRecord:
    config_id: str
    provider: str
    model_name: str
    task_type: str
    outcome: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    attempt_count: int
    fallback_used: bool
    trace_id: str
    run_id: str | None
    error_code: str | None
    created_at: datetime


class UsageRecorder:
    """Thread-safe bounded in-process usage sink; persistence adapters may subscribe later."""

    def __init__(self, max_records: int = 2_000) -> None:
        self._max_records = max_records
        self._records: list[UsageRecord] = []
        self._lock = Lock()

    def record(self, record: UsageRecord) -> None:
        with self._lock:
            self._records.append(record)
            if len(self._records) > self._max_records:
                del self._records[: len(self._records) - self._max_records]

    def snapshot(self) -> tuple[UsageRecord, ...]:
        with self._lock:
            return tuple(self._records)

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)
