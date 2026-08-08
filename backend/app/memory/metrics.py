from __future__ import annotations

import threading
from collections import defaultdict


class MemoryLifecycleMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, int] = defaultdict(int)
        self._transitions: dict[str, int] = defaultdict(int)
        self._last_success_timestamp = 0.0

    def observe_run(self, status: str, *, transitions: dict[str, int] | None = None, timestamp: float = 0.0) -> None:
        with self._lock:
            self._runs[status.lower()] += 1
            for name, count in (transitions or {}).items():
                self._transitions[name.lower()] += int(count)
            if status.upper() == "COMPLETED":
                self._last_success_timestamp = timestamp

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "runs": dict(self._runs),
                "transitions": dict(self._transitions),
                "last_success_timestamp": self._last_success_timestamp,
            }

    def render(self) -> str:
        snapshot = self.snapshot()
        lines = [
            "# HELP renewable_memory_lifecycle_runs_total Memory lifecycle worker runs by terminal outcome.",
            "# TYPE renewable_memory_lifecycle_runs_total counter",
        ]
        lines.extend(
            f'renewable_memory_lifecycle_runs_total{{status="{status}"}} {count}'
            for status, count in sorted(snapshot["runs"].items())
        )
        lines.extend([
            "# HELP renewable_memory_lifecycle_transitions_total Memory lifecycle record transitions.",
            "# TYPE renewable_memory_lifecycle_transitions_total counter",
        ])
        lines.extend(
            f'renewable_memory_lifecycle_transitions_total{{transition="{name}"}} {count}'
            for name, count in sorted(snapshot["transitions"].items())
        )
        lines.extend([
            "# HELP renewable_memory_lifecycle_last_success_timestamp_seconds Last successful lifecycle task timestamp.",
            "# TYPE renewable_memory_lifecycle_last_success_timestamp_seconds gauge",
            f'renewable_memory_lifecycle_last_success_timestamp_seconds {snapshot["last_success_timestamp"]:.3f}',
            "",
        ])
        return "\n".join(lines)


memory_lifecycle_metrics = MemoryLifecycleMetrics()
