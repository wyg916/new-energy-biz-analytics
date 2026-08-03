"""Run the P5 representative capacity workload against an authorized acceptance stack.

The default is a two-hour, 20-worker run. Results are acceptance-environment
measurements and can never authorize a production SLA or traffic switch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from run_p4_capacity_soak import database_snapshot, process_rss_bytes, redis_snapshot, token_for
from app.core.database import SessionLocal
from app.core.config import get_settings
from app.core.security import create_access_token
from app.governance.models import Principal
from app.models.auth import User
from app.preproduction.oidc import OIDCFlowError, OIDCSessionStore


CASES = (
    ("deterministic_dashboard", "GET", "/api/v1/dashboard/summary?start=2026-05-01&end_exclusive=2026-07-01", None, 200),
    ("deterministic_dashboard", "GET", "/api/v1/dashboard/stations?start=2026-05-01&end_exclusive=2026-07-01", None, 200),
    ("deterministic_dashboard", "GET", "/api/v1/dashboard/trend?metric=charging_revenue&start=2026-05-01&end_exclusive=2026-07-01", None, 200),
    ("deterministic_dashboard", "GET", "/api/v1/dashboard/summary?start=2026-01-01&end_exclusive=2026-07-01", None, 200),
    ("deterministic_dashboard", "GET", "/api/v1/dashboard/devices?start=2026-05-01&end_exclusive=2026-07-01", None, 200),
    ("deterministic_assistant_charging_total", "POST", "/api/v1/assistant/query", {"question": "2026年6月充电收入是多少？", "scenario_id": "charging_ops", "profile": "executive_brief"}, 200),
    ("deterministic_assistant_station_ranking", "POST", "/api/v1/assistant/query", {"question": "2026年6月区域A充电收入最高的5个场站。", "scenario_id": "charging_ops", "profile": "executive_brief"}, 200),
    ("deterministic_assistant_sales_total", "POST", "/api/v1/assistant/query", {"question": "2026年6月销售收入是多少？", "scenario_id": "sales_ops", "profile": "executive_brief"}, 200),
    ("deterministic_assistant_gross_profit", "POST", "/api/v1/assistant/query", {"question": "2026年6月经营毛利是多少？", "scenario_id": "charging_ops", "profile": "analyst_detailed"}, 200),
    ("identity_and_policy", "GET", "/api/v1/auth/me", None, 200),
    ("identity_and_policy", "GET", "/api/v1/chat/scenarios", None, 200),
    ("identity_and_policy", "GET", "/api/v1/governance/snapshot", None, 200),
    ("permission_guard", "GET", "/api/v1/auth/admin-check", None, 401),
    ("memory", "GET", "/api/v1/memory/records?scenario_id=charging_ops", None, 200),
    ("memory", "GET", "/api/v1/memory/records?scenario_id=sales_ops", None, 200),
    ("skill", "GET", "/api/v1/skills?scenario_id=charging_ops", None, 200),
    ("skill", "GET", "/api/v1/skills?scenario_id=sales_ops", None, 200),
    ("rag_keyword", "GET", "/api/v1/knowledge/runtime", None, 200),
    ("rag_keyword", "GET", "/api/v1/knowledge/documents?scenario_id=charging_ops", None, 200),
    ("production_acceptance", "GET", "/api/v1/production-acceptance/snapshot", None, 200),
    ("oidc_status", "GET", "/api/v1/auth/oidc/status", None, 200),
)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)], 3)


def cpu_usage_seconds() -> float:
    try:
        fields = Path("/proc/1/stat").read_text(encoding="utf-8").split()
        ticks = int(fields[13]) + int(fields[14])
        return round(ticks / 100.0, 3)
    except (OSError, ValueError, IndexError):
        return 0.0


def revoke_session_if_present(session_id: str) -> bool:
    """Revoke an acceptance session without failing after natural TTL expiry."""
    try:
        OIDCSessionStore().revoke_session(session_id)
        return True
    except OIDCFlowError as exc:
        if exc.code == "OIDC_SESSION_INVALID":
            return False
        raise


def denied_credentials() -> tuple[str, str]:
    """Create a fresh LOCAL session used only for the expected-401 control."""
    with SessionLocal() as db:
        denied_user = db.scalar(select(User).where(
            User.username == "regional", User.is_active.is_(True),
        ))
        denied_principal = db.scalar(select(Principal).where(
            Principal.local_user_id == denied_user.id,
            Principal.provider_code == "LOCAL",
            Principal.status == "ACTIVE",
        )) if denied_user is not None else None
        if denied_user is None or denied_principal is None:
            raise RuntimeError("local negative-test principal unavailable")
        denied_session_id = OIDCSessionStore().create_session(
            principal_id=denied_principal.principal_id,
            user_id=denied_user.id,
            groups=("regional",),
            refresh_token="",
        )
        denied_token = create_access_token(
            denied_user.id,
            denied_user.role,
            auth_provider=denied_principal.provider_code,
            principal_id=denied_principal.principal_id,
            session_id=denied_session_id,
        )
    return denied_token, denied_session_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://p5a.localhost:8445")
    parser.add_argument(
        "--request-host",
        help="HTTP Host header when the connection target uses an internal DNS name",
    )
    parser.add_argument("--duration-seconds", type=int, default=7200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--logical-users", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.duration_seconds < 60 or not 1 <= args.concurrency <= 64:
        parser.error("duration must be >= 60 seconds and concurrency between 1 and 64")
    if args.logical_users < args.concurrency or args.logical_users > 500:
        parser.error("logical users must be between concurrency and 500")

    request_host = args.request_host or urlparse(args.base_url).hostname or "p5a.localhost"
    started_at = datetime.now(UTC)
    deadline = time.monotonic() + args.duration_seconds
    initial_db, initial_redis = database_snapshot(), redis_snapshot()
    initial_cpu = cpu_usage_seconds()
    latencies: list[float] = []
    workload_latencies: dict[str, list[float]] = defaultdict(list)
    statuses: Counter[int] = Counter()
    expected_statuses: Counter[str] = Counter()
    workloads: Counter[str] = Counter()
    workload_statuses: dict[str, Counter[int]] = defaultdict(Counter)
    endpoint_statuses: dict[str, Counter[int]] = defaultdict(Counter)
    resource_samples: list[dict] = []
    resource_sample_errors: list[str] = []
    lock, stop = threading.Lock(), threading.Event()
    settings = get_settings()
    session_rotation_seconds = max(60, settings.oidc_session_ttl_seconds - 120)
    identities = []
    for logical_user in range(args.logical_users):
        token, session_id = token_for("analyst")
        denied_token, denied_session_id = denied_credentials()
        identities.append({
            "logical_user": logical_user,
            "token": token,
            "session_id": session_id,
            "refresh_at": time.monotonic() + 300,
            "rotate_at": time.monotonic() + session_rotation_seconds,
            "denied_token": denied_token,
            "denied_session_id": denied_session_id,
        })

    session_rotation_count = 0
    worker_errors: list[str] = []

    def worker(offset: int) -> None:
        index = offset
        with httpx.Client(base_url=args.base_url, timeout=args.timeout_seconds, verify=False) as client:
            while not stop.is_set() and time.monotonic() < deadline:
                identity = identities[index % args.logical_users]
                now = time.monotonic()
                if now >= identity["rotate_at"]:
                    revoke_session_if_present(identity["session_id"])
                    revoke_session_if_present(identity["denied_session_id"])
                    identity["token"], identity["session_id"] = token_for("analyst")
                    identity["denied_token"], identity["denied_session_id"] = denied_credentials()
                    identity["refresh_at"] = now + 300
                    identity["rotate_at"] = now + session_rotation_seconds
                    with lock:
                        nonlocal session_rotation_count
                        session_rotation_count += 1
                elif now >= identity["refresh_at"]:
                    identity["token"], _ = token_for(
                        "analyst", session_id=identity["session_id"],
                    )
                    identity["refresh_at"] = time.monotonic() + 300
                name, method, path, payload, expected_status = CASES[index % len(CASES)]
                request_token = (
                    identity["denied_token"] if name == "permission_guard" else identity["token"]
                )
                body = dict(payload) if payload else None
                if body is not None:
                    body["conversation_id"] = (
                        f"p5-capacity-{identity['logical_user']}-{body.get('scenario_id', 'general')}"
                    )
                started = time.perf_counter()
                try:
                    response = client.request(
                        method,
                        path,
                        headers={
                            "Authorization": f"Bearer {request_token}",
                            "Host": request_host,
                        },
                        json=body,
                    )
                    status = response.status_code
                except httpx.TimeoutException:
                    status = 0
                except httpx.HTTPError:
                    status = -1
                latency = (time.perf_counter() - started) * 1000
                with lock:
                    statuses[status] += 1
                    expected_statuses[f"{expected_status}:{status}"] += 1
                    endpoint_statuses[path][status] += 1
                    workloads[name] += 1
                    workload_statuses[name][status] += 1
                    latencies.append(latency)
                    workload_latencies[name].append(latency)
                index += args.concurrency

    try:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = [executor.submit(worker, offset) for offset in range(args.concurrency)]
            while time.monotonic() < deadline:
                sample = {
                    "elapsed_seconds": round(args.duration_seconds - (deadline - time.monotonic()), 1),
                    "api_rss_bytes": process_rss_bytes(),
                    "api_cpu_seconds": cpu_usage_seconds(),
                }
                try:
                    sample["database"] = database_snapshot()
                    sample["redis"] = redis_snapshot()
                except Exception as exc:  # evidence records sampler failures without hiding workload results
                    resource_sample_errors.append(type(exc).__name__)
                resource_samples.append(sample)
                time.sleep(min(10, max(0.01, deadline - time.monotonic())))
            stop.set()
            for future in futures:
                try:
                    future.result()
                except Exception as exc:
                    worker_errors.append(type(exc).__name__)
    finally:
        for identity in identities:
            try:
                revoke_session_if_present(identity["session_id"])
                revoke_session_if_present(identity["denied_session_id"])
            except Exception as exc:
                worker_errors.append(f"session_cleanup:{type(exc).__name__}")

    final_db, final_redis = database_snapshot(), redis_snapshot()
    total = len(latencies)
    errors = sum(
        count for pair, count in expected_statuses.items()
        if pair.split(":", 1)[0] != pair.split(":", 1)[1]
    )
    timeouts = statuses.get(0, 0)
    security_violation_successes = sum(
        count for path, counts in endpoint_statuses.items()
        if path == "/api/v1/auth/admin-check" for status, count in counts.items() if status == 200
    )
    rss = [sample["api_rss_bytes"] for sample in resource_samples if sample["api_rss_bytes"]]
    db_connections = [
        sample["database"]["connections"] for sample in resource_samples if "database" in sample
    ]
    redis_clients = [
        sample["redis"]["connected_clients"] for sample in resource_samples if "redis" in sample
    ]
    report = {
        "evidence_type": "p5_production_acceptance_capacity",
        "run_id": f"P5-CAP-{started_at.strftime('%Y%m%dT%H%M%SZ')}",
        "status": "PASS" if total and errors / total <= 0.01 and timeouts / total <= 0.005 else "FAIL",
        "environment_boundary": "production-acceptance-not-production-sla",
        "production_capacity_verified": False,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "configured_duration_seconds": args.duration_seconds,
        "concurrency": args.concurrency,
        "logical_users": args.logical_users,
        "total_requests": total,
        "workloads": dict(sorted(workloads.items())),
        "workload_status_counts": {
            name: {str(status): count for status, count in sorted(counts.items())}
            for name, counts in sorted(workload_statuses.items())
        },
        "status_counts": {str(k): v for k, v in sorted(statuses.items())},
        "expected_actual_status_counts": dict(sorted(expected_statuses.items())),
        "endpoint_status_counts": {
            path: {str(status): count for status, count in sorted(counts.items())}
            for path, counts in sorted(endpoint_statuses.items())
        },
        "p50_ms": round(statistics.median(latencies), 3) if latencies else 0,
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "error_rate": round(errors / total, 6) if total else 1.0,
        "timeout_rate": round(timeouts / total, 6) if total else 1.0,
        "workload_p95_ms": {name: percentile(values, 0.95) for name, values in sorted(workload_latencies.items())},
        "api_resources": {"initial_rss_bytes": rss[0] if rss else 0, "final_rss_bytes": rss[-1] if rss else 0, "growth_bytes": rss[-1] - rss[0] if len(rss) > 1 else 0, "cpu_seconds": round(cpu_usage_seconds() - initial_cpu, 3)},
        "postgresql": {
            "initial": initial_db,
            "final": final_db,
            "growth_bytes": final_db["size_bytes"] - initial_db["size_bytes"],
            "peak_connections": max(db_connections, default=final_db["connections"]),
        },
        "redis": {
            "initial": initial_redis,
            "final": final_redis,
            "peak_connected_clients": max(redis_clients, default=final_redis["connected_clients"]),
        },
        "resource_sample_count": len(resource_samples),
        "resource_sample_errors": resource_sample_errors,
        "worker_errors": worker_errors,
        "session_ttl_seconds": settings.oidc_session_ttl_seconds,
        "session_rotation_lead_seconds": settings.oidc_session_ttl_seconds - session_rotation_seconds,
        "session_rotation_count": session_rotation_count,
        "audit_backlog": "must_be_correlated_with_fault_run",
        "rolling_restart": "separate_fault_step_required",
        "single_instance_failure": "separate_fault_step_required",
        "backup_impact": "separate_fault_step_required",
        "production_release_authorized": False,
        "production_traffic_switched": False,
        "security_violation_successes": security_violation_successes,
    }
    report["status"] = "PASS" if (
        total and errors / total <= 0.01 and timeouts / total <= 0.005
        and security_violation_successes == 0 and not resource_sample_errors and not worker_errors
    ) else "FAIL"
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps({"status": report["status"], "run_id": report["run_id"], "sha256": hashlib.sha256(serialized.encode()).hexdigest()}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
