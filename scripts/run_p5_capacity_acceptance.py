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

import httpx

from run_p4_capacity_soak import database_snapshot, process_rss_bytes, redis_snapshot, token_for
from app.preproduction.oidc import OIDCSessionStore


CASES = (
    ("deterministic_dashboard", "GET", "/api/v1/dashboard/summary?start=2026-05-01&end_exclusive=2026-07-01", None),
    ("deterministic_dashboard", "GET", "/api/v1/dashboard/stations?start=2026-05-01&end_exclusive=2026-07-01", None),
    ("deterministic_dashboard", "GET", "/api/v1/dashboard/trend?start=2026-05-01&end_exclusive=2026-07-01", None),
    ("deterministic_dashboard", "GET", "/api/v1/dashboard/summary?start=2026-01-01&end_exclusive=2026-07-01", None),
    ("deterministic_dashboard", "GET", "/api/v1/dashboard/devices?start=2026-05-01&end_exclusive=2026-07-01", None),
    ("deterministic_assistant", "POST", "/api/v1/assistant/query", {"question": "2026年5月至6月充电收入是多少？", "scenario_id": "charging_ops", "profile": "executive_brief"}),
    ("deterministic_assistant", "POST", "/api/v1/assistant/query", {"question": "比较各区域充电收入", "scenario_id": "charging_ops", "profile": "executive_brief"}),
    ("deterministic_assistant", "POST", "/api/v1/assistant/query", {"question": "销售收入趋势", "scenario_id": "sales_ops", "profile": "executive_brief"}),
    ("deterministic_assistant", "POST", "/api/v1/assistant/query", {"question": "分析场站利用率", "scenario_id": "charging_ops", "profile": "analyst_detail"}),
    ("identity_and_policy", "GET", "/api/v1/auth/me", None),
    ("identity_and_policy", "GET", "/api/v1/chat/scenarios", None),
    ("identity_and_policy", "GET", "/api/v1/governance/snapshot", None),
    ("memory", "GET", "/api/v1/memory/records?scenario_id=charging_ops", None),
    ("memory", "GET", "/api/v1/memory/records?scenario_id=sales_ops", None),
    ("skill", "GET", "/api/v1/skills?scenario_id=charging_ops", None),
    ("skill", "GET", "/api/v1/skills?scenario_id=sales_ops", None),
    ("rag_keyword", "GET", "/api/v1/knowledge/runtime", None),
    ("rag_keyword", "GET", "/api/v1/knowledge/documents?scenario_id=charging_ops", None),
    ("production_acceptance", "GET", "/api/v1/production-acceptance/snapshot", None),
    ("oidc_status", "GET", "/api/v1/auth/oidc/status", None),
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://p4.localhost:8444")
    parser.add_argument("--duration-seconds", type=int, default=7200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.duration_seconds < 60 or not 1 <= args.concurrency <= 64:
        parser.error("duration must be >= 60 seconds and concurrency between 1 and 64")

    started_at = datetime.now(UTC)
    deadline = time.monotonic() + args.duration_seconds
    initial_db, initial_redis = database_snapshot(), redis_snapshot()
    initial_cpu = cpu_usage_seconds()
    latencies: list[float] = []
    workload_latencies: dict[str, list[float]] = defaultdict(list)
    statuses: Counter[int] = Counter()
    workloads: Counter[str] = Counter()
    resource_samples: list[dict] = []
    lock, stop = threading.Lock(), threading.Event()

    def worker(offset: int) -> None:
        token, session_id = token_for("analyst")
        index = offset
        try:
            with httpx.Client(base_url=args.base_url, timeout=args.timeout_seconds, verify=False) as client:
                while not stop.is_set() and time.monotonic() < deadline:
                    name, method, path, payload = CASES[index % len(CASES)]
                    body = dict(payload) if payload else None
                    if body is not None:
                        body["conversation_id"] = f"p5-capacity-{threading.get_ident()}"
                    started = time.perf_counter()
                    try:
                        response = client.request(method, path, headers={"Authorization": f"Bearer {token}", "Host": "p4.localhost"}, json=body)
                        status = response.status_code
                    except httpx.TimeoutException:
                        status = 0
                    except httpx.HTTPError:
                        status = -1
                    latency = (time.perf_counter() - started) * 1000
                    with lock:
                        statuses[status] += 1
                        workloads[name] += 1
                        latencies.append(latency)
                        workload_latencies[name].append(latency)
                    index += args.concurrency
        finally:
            OIDCSessionStore().revoke_session(session_id)

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(worker, offset) for offset in range(args.concurrency)]
        while time.monotonic() < deadline:
            resource_samples.append({"elapsed_seconds": round(args.duration_seconds - (deadline - time.monotonic()), 1), "api_rss_bytes": process_rss_bytes(), "api_cpu_seconds": cpu_usage_seconds()})
            time.sleep(min(10, max(0.01, deadline - time.monotonic())))
        stop.set()
        for future in futures:
            future.result()

    final_db, final_redis = database_snapshot(), redis_snapshot()
    total = len(latencies)
    errors = sum(count for status, count in statuses.items() if status != 200)
    timeouts = statuses.get(0, 0)
    rss = [sample["api_rss_bytes"] for sample in resource_samples if sample["api_rss_bytes"]]
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
        "total_requests": total,
        "workloads": dict(sorted(workloads.items())),
        "status_counts": {str(k): v for k, v in sorted(statuses.items())},
        "p50_ms": round(statistics.median(latencies), 3) if latencies else 0,
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "error_rate": round(errors / total, 6) if total else 1.0,
        "timeout_rate": round(timeouts / total, 6) if total else 1.0,
        "workload_p95_ms": {name: percentile(values, 0.95) for name, values in sorted(workload_latencies.items())},
        "api_resources": {"initial_rss_bytes": rss[0] if rss else 0, "final_rss_bytes": rss[-1] if rss else 0, "growth_bytes": rss[-1] - rss[0] if len(rss) > 1 else 0, "cpu_seconds": round(cpu_usage_seconds() - initial_cpu, 3)},
        "postgresql": {"initial": initial_db, "final": final_db, "growth_bytes": final_db["size_bytes"] - initial_db["size_bytes"]},
        "redis": {"initial": initial_redis, "final": final_redis},
        "audit_backlog": "must_be_correlated_with_fault_run",
        "rolling_restart": "separate_fault_step_required",
        "single_instance_failure": "separate_fault_step_required",
        "backup_impact": "separate_fault_step_required",
        "production_release_authorized": False,
        "production_traffic_switched": False,
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps({"status": report["status"], "run_id": report["run_id"], "sha256": hashlib.sha256(serialized.encode()).hexdigest()}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
