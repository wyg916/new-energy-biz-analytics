from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock

from app.query_engines.sqlbot.error_mapper import (
    SQLBotEngineError,
    SQLBotErrorCode,
)


@dataclass
class CircuitState:
    failures: int = 0
    opened_at: datetime | None = None
    half_open_probe: bool = False


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_seconds: int = 30):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        self.failure_threshold = failure_threshold
        self.recovery = timedelta(seconds=recovery_seconds)
        self.state = CircuitState()
        self._lock = RLock()

    def before_call(self) -> None:
        now = datetime.now(UTC)
        with self._lock:
            if self.state.opened_at is None:
                return
            if now - self.state.opened_at < self.recovery:
                raise SQLBotEngineError(
                    SQLBotErrorCode.CIRCUIT_OPEN,
                    "SQLBot 熔断器已打开",
                    retryable=True,
                )
            if self.state.half_open_probe:
                raise SQLBotEngineError(
                    SQLBotErrorCode.CIRCUIT_OPEN,
                    "SQLBot 熔断器等待探测结果",
                    retryable=True,
                )
            self.state.half_open_probe = True

    def record_success(self) -> None:
        with self._lock:
            self.state = CircuitState()

    def record_failure(self) -> None:
        with self._lock:
            self.state.failures += 1
            self.state.half_open_probe = False
            if self.state.failures >= self.failure_threshold:
                self.state.opened_at = datetime.now(UTC)

    @property
    def status(self) -> str:
        return "open" if self.state.opened_at else "closed"
