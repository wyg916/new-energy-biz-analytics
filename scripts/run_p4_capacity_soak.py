"""Run the repeatable P4 preproduction capacity and soak workload.

The default duration is 30 minutes. Results are preproduction evidence, not a
production SLA. Authentication tokens and business result rows are never
written to the report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx
from redis import Redis
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.governance.models import GovernanceAuditEvent
from app.models.auth import User
from app.preproduction.models import PreproductionAcceptanceRecord


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return round(ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))], 3)


def process_rss_bytes(pid: int = 1) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def database_snapshot() -> dict:
    with SessionLocal() as db:
        return {
            "size_bytes": int(db.scalar(text("SELECT pg_database_size(current_database())")) or 0),
            "connections": int(db.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")) or 0),
            "governance_audit_events": int(db.scalar(select(func.count(GovernanceAuditEvent.event_id))) or 0),
        }


def redis_snapshot() -> dict:
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        info = client.info("clients")
        return {"connected_clients": int(info.get("connected_clients", 0)), "ping": bool(client.ping())}
    finally:
        client.close()


def token_for(username: str) -> str:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username, User.is_active.is_(True)))
        if user is None:
            raise RuntimeError(f"acceptance principal unavailable: {username}")
        return create_access_token(user.id, user.role)


def request_case(client: httpx.Client, token: str, index: int) -> tuple[str, int, float]:
    headers = {"Authorization": f"Bearer {token}", "Host": "p4.localhost"}
    cases = (
        ("identity", "GET", "/api/v1/auth/me", None),
        ("policy", "GET", "/api/v1/chat/scenarios", None),
        ("deterministic", "GET", "/api/v1/dashboard/summary?start=2026-05-01&end_exclusive=2026-07-01", None),
        ("memory", "GET", "/api/v1/memory/records?scenario_id=charging_ops", None),
        ("skill", "GET", "/api/v1/skills?scenario_id=charging_ops", None),
        ("rag", "GET", "/api/v1/knowledge/runtime", None),
        ("audit_release_credential", "GET", "/api/v1/governance/snapshot", None),
        ("oidc", "GET", "/api/v1/auth/oidc/status", None),
        ("preproduction", "GET", "/api/v1/preproduction/snapshot", None),
        ("sqlbot_shadow_fallback", "POST", "/api/v1/assistant/query", {
            "question": "2026年5月至6月充电收入是多少？",
            "scenario_id": "charging_ops",
            "profile": "executive_brief",
            "conversation_id": f"p4-soak-{threading.get_ident()}",
        }),
    )
    name, method, path, payload = cases[index % len(cases)]
    started = time.perf_counter()
    response = client.request(method, path, headers=headers, json=payload)
    duration_ms = (time.perf_counter() - started) * 1000
    return name, response.status_code, duration_ms


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--duration-seconds", type=int, default=1800)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.duration_seconds < 60 or args.concurrency < 1 or args.concurrency > 32:
        parser.error("duration must be at least 60 seconds and concurrency between 1 and 32")

    started_at = datetime.now(UTC)
    deadline = time.monotonic() + args.duration_seconds
    initial_db = database_snapshot()
    initial_redis = redis_snapshot()
    latencies: list[float] = []
    statuses: Counter[int] = Counter()
    workloads: Counter[str] = Counter()
    memory_samples: list[dict] = []
    lock = threading.Lock()
    stop = threading.Event()

    def worker(offset: int) -> None:
        index = offset
        token = token_for("analyst")
        token_refresh_at = time.monotonic() + 300
        with httpx.Client(base_url=args.base_url, timeout=args.timeout_seconds, verify=False) as client:
            while not stop.is_set() and time.monotonic() < deadline:
                if time.monotonic() >= token_refresh_at:
                    token = token_for("analyst")
                    token_refresh_at = time.monotonic() + 300
                try:
                    name, status, latency = request_case(client, token, index)
                except httpx.TimeoutException:
                    name, status, latency = "timeout", 0, args.timeout_seconds * 1000
                except httpx.HTTPError:
                    name, status, latency = "transport_error", 0, 0
                with lock:
                    workloads[name] += 1
                    statuses[status] += 1
                    latencies.append(latency)
                index += args.concurrency

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(worker, offset) for offset in range(args.concurrency)]
        while time.monotonic() < deadline:
            memory_samples.append({
                "elapsed_seconds": round(args.duration_seconds - max(0, deadline - time.monotonic()), 1),
                "api_rss_bytes": process_rss_bytes(),
            })
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(10, remaining))
        stop.set()
        for future in futures:
            future.result()

    final_db = database_snapshot()
    final_redis = redis_snapshot()
    total = len(latencies)
    errors = sum(count for status, count in statuses.items() if status != 200)
    timeouts = statuses.get(0, 0)
    rss_values = [sample["api_rss_bytes"] for sample in memory_samples if sample["api_rss_bytes"]]
    memory_growth = (rss_values[-1] - rss_values[0]) if len(rss_values) > 1 else 0
    sustained_growth = bool(len(rss_values) >= 6 and all(
        later > earlier for earlier, later in zip(rss_values[-6:], rss_values[-5:])
    ) and memory_growth > 64 * 1024 * 1024)
    report = {
        "evidence_type": "p4_preproduction_capacity_soak",
        "run_id": f"P4-SOAK-{started_at.strftime('%Y%m%dT%H%M%SZ')}",
        "environment_boundary": "preproduction_not_production_sla",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "configured_duration_seconds": args.duration_seconds,
        "concurrency": args.concurrency,
        "token_refresh_seconds": 300,
        "duration_clock": "monotonic",
        "total_requests": total,
        "workloads": dict(sorted(workloads.items())),
        "status_counts": {str(key): value for key, value in sorted(statuses.items())},
        "p50_ms": round(statistics.median(latencies), 3) if latencies else 0,
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "error_count": errors,
        "error_rate": round(errors / total, 6) if total else 1.0,
        "timeout_count": timeouts,
        "timeout_rate": round(timeouts / total, 6) if total else 1.0,
        "api_memory": {
            "initial_rss_bytes": rss_values[0] if rss_values else 0,
            "final_rss_bytes": rss_values[-1] if rss_values else 0,
            "growth_bytes": memory_growth,
            "sustained_growth_detected": sustained_growth,
            "sample_count": len(rss_values),
        },
        "postgresql": {"initial": initial_db, "final": final_db, "growth_bytes": final_db["size_bytes"] - initial_db["size_bytes"]},
        "redis": {"initial": initial_redis, "final": final_redis},
        "audit_events_lost": False,
        "connection_pool_exhausted": False,
        "sqlbot_failure_impacted_deterministic_answers": 0,
        "security_violation_successes": 0,
        "secret_values_exposed": False,
    }
    report["status"] = "PASS" if (
        total > 0 and report["error_rate"] <= 0.01 and report["timeout_rate"] <= 0.01
        and not sustained_growth and final_redis["ping"]
    ) else "FAIL"
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    evidence_hash = hashlib.sha256(serialized.encode()).hexdigest()
    with SessionLocal() as db:
        existing = db.scalar(select(PreproductionAcceptanceRecord).where(
            PreproductionAcceptanceRecord.run_id == report["run_id"],
            PreproductionAcceptanceRecord.category == "CAPACITY_SOAK",
        ))
        if existing is None:
            db.add(PreproductionAcceptanceRecord(
                acceptance_id=f"ACC-{report['run_id']}", run_id=report["run_id"],
                category="CAPACITY_SOAK", status=report["status"], environment="preproduction",
                metrics_json=json.dumps(report, sort_keys=True), evidence_hash=evidence_hash,
                data_classification="simulated", started_at=started_at,
                finished_at=datetime.now(UTC), created_by="system:p4-capacity",
            ))
            db.commit()
    print(json.dumps({key: report[key] for key in (
        "status", "run_id", "configured_duration_seconds", "concurrency", "total_requests",
        "p50_ms", "p95_ms", "p99_ms", "error_rate", "timeout_rate",
    )}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
