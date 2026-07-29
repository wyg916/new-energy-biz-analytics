from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any

from redis import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine


PROCESS_STARTED_AT = time.time()


class RequestMetrics:
    """In-process, low-cardinality HTTP metrics for a single private instance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str], int] = defaultdict(int)
        self._duration_seconds_sum = 0.0
        self._duration_seconds_count = 0

    def observe(self, method: str, status_code: int, duration_seconds: float) -> None:
        status_class = f"{status_code // 100}xx"
        with self._lock:
            self._requests[(method.upper(), status_class)] += 1
            self._duration_seconds_sum += duration_seconds
            self._duration_seconds_count += 1

    def render(self) -> str:
        with self._lock:
            requests = sorted(self._requests.items())
            duration_sum = self._duration_seconds_sum
            duration_count = self._duration_seconds_count
        lines = [
            "# HELP renewable_api_process_start_time_seconds Unix timestamp when the API process started.",
            "# TYPE renewable_api_process_start_time_seconds gauge",
            f"renewable_api_process_start_time_seconds {PROCESS_STARTED_AT:.3f}",
            "# HELP renewable_api_http_requests_total Total HTTP requests grouped by method and status class.",
            "# TYPE renewable_api_http_requests_total counter",
        ]
        lines.extend(
            f'renewable_api_http_requests_total{{method="{method}",status_class="{status_class}"}} {count}'
            for (method, status_class), count in requests
        )
        lines.extend([
            "# HELP renewable_api_http_request_duration_seconds Request duration accumulated across all routes.",
            "# TYPE renewable_api_http_request_duration_seconds summary",
            f"renewable_api_http_request_duration_seconds_sum {duration_sum:.6f}",
            f"renewable_api_http_request_duration_seconds_count {duration_count}",
            "",
        ])
        return "\n".join(lines)


request_metrics = RequestMetrics()


def readiness_snapshot() -> tuple[dict[str, Any], int]:
    settings = get_settings()
    components: dict[str, dict[str, Any]] = {}

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        revision_ok = revision == settings.expected_database_revision
        components["database"] = {
            "status": "ok" if revision_ok else "revision_mismatch",
            "revision": revision,
            "expected_revision": settings.expected_database_revision,
        }
    except Exception:
        components["database"] = {"status": "unavailable"}

    redis_client: Redis | None = None
    try:
        redis_client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        components["redis"] = {"status": "ok" if redis_client.ping() else "unavailable"}
    except Exception:
        components["redis"] = {"status": "unavailable"}
    finally:
        if redis_client is not None:
            redis_client.close()

    ready = all(component["status"] == "ok" for component in components.values())
    payload = {
        "status": "ready" if ready else "not_ready",
        "service": "renewable-operations-api",
        "release_version": settings.release_version,
        "data_classification": "simulated",
        "components": components,
    }
    return payload, 200 if ready else 503
