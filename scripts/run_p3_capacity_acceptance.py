"""Repeatable isolated-environment concurrency probe for P3 control paths.

This is not a production load test and its output is not an SLA. It creates
short-lived signed test tokens from already-seeded local users and never prints
tokens, passwords, connection strings, business rows, or Secret values.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.auth import User


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile_value * len(ordered)) - 1))
    return round(ordered[index], 3)


def token_for(username: str) -> str:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username, User.is_active.is_(True)))
        if user is None:
            raise RuntimeError(f"required local acceptance principal is unavailable: {username}")
        return create_access_token(user.id, user.role)


def call(base_url: str, token: str, workload: str, timeout: float) -> tuple[float, int]:
    started = time.perf_counter()
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        if workload == "identity_middleware":
            response = client.get("/api/v1/auth/me", headers=headers)
        elif workload == "policy_engine":
            response = client.get("/api/v1/chat/scenarios", headers=headers)
        elif workload == "memory_query":
            response = client.get("/api/v1/memory/records?scenario_id=charging_ops", headers=headers)
        elif workload == "skill_execution":
            response = client.post(
                "/api/v1/skills/execute",
                headers=headers,
                json={
                    "skill_code": "revenue_decline_diagnosis",
                    "scenario_id": "charging_ops",
                    "start": "2026-05-01",
                    "end_exclusive": "2026-07-01",
                    "comparison": "mom",
                    "limit": 5,
                },
            )
        else:
            response = client.get("/api/v1/governance/snapshot", headers=headers)
    return (time.perf_counter() - started) * 1000, response.status_code


def run_workload(
    base_url: str,
    token: str,
    workload: str,
    *,
    concurrency: int,
    request_count: int,
    timeout: float,
    expected_status: int,
) -> dict[str, Any]:
    samples: list[float] = []
    statuses: list[int] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(call, base_url, token, workload, timeout) for _ in range(request_count)]
        for future in as_completed(futures):
            latency, status = future.result()
            samples.append(latency)
            statuses.append(status)
    errors = sum(status != expected_status for status in statuses)
    return {
        "workload": workload,
        "concurrency": concurrency,
        "request_count": request_count,
        "expected_http_status": expected_status,
        "status_counts": {str(code): statuses.count(code) for code in sorted(set(statuses))},
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": percentile(samples, 0.95),
        "error_count": errors,
        "error_rate": round(errors / request_count, 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=4, choices=range(1, 33))
    parser.add_argument("--requests", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.requests < args.concurrency:
        parser.error("--requests must be greater than or equal to --concurrency")

    admin_token = token_for("analyst")
    executive_token = token_for("executive")
    workloads = [
        run_workload(args.base_url, admin_token, name, concurrency=args.concurrency, request_count=args.requests, timeout=args.timeout, expected_status=200)
        for name in ("identity_middleware", "policy_engine", "memory_query", "skill_execution")
    ]
    workloads.append(run_workload(
        args.base_url,
        executive_token,
        "audit_write_denial",
        concurrency=args.concurrency,
        request_count=args.requests,
        timeout=args.timeout,
        expected_status=403,
    ))
    report = {
        "evidence_type": "p3_isolated_capacity_acceptance",
        "environment_boundary": "isolated_local_test_not_production_sla",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "base_url_redacted": True,
        "concurrency": args.concurrency,
        "requests_per_workload": args.requests,
        "workloads": workloads,
        "total_requests": sum(item["request_count"] for item in workloads),
        "total_errors": sum(item["error_count"] for item in workloads),
        "secret_values_exposed": False,
        "business_rows_exposed": False,
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    if report["total_errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
