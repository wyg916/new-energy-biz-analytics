"""Independently validate a completed P5A two-hour capacity evidence file."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "docs" / "platformization" / "p5a" / "evidence" / "p5a-capacity-soak.json"
DEFAULT_OUTPUT = ROOT / "docs" / "platformization" / "p5a" / "evidence" / "p5a-capacity-verification.json"
WORKLOAD_SOURCE = ROOT / "scripts" / "run_p5_capacity_acceptance.py"
REQUIRED_SERVICES = {"api", "db", "redis", "oidc", "vault"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    raw_bytes = args.input.read_bytes()
    payload = json.loads(raw_bytes)
    pairs = payload.get("expected_actual_status_counts") or {}
    success_count = sum(
        int(count) for pair, count in pairs.items()
        if pair.split(":", 1)[0] == pair.split(":", 1)[1]
    )
    error_count = sum(int(count) for count in pairs.values()) - success_count
    timeout_count = int((payload.get("status_counts") or {}).get("0", 0))
    total = int(payload.get("total_requests") or 0)
    host = payload.get("host_monitor") or {}
    invariants = payload.get("acceptance_invariants") or {}
    resources = host.get("container_resources") or {}
    restarts = host.get("restart_counts") or {}
    source_sha256 = hashlib.sha256(WORKLOAD_SOURCE.read_bytes()).hexdigest()
    checks = {
        "workload_status_pass": payload.get("status") == "PASS",
        "duration_configuration_exact": payload.get("configured_duration_seconds") == 7200,
        "actual_duration_met": float(host.get("actual_duration_seconds") or 0) >= 7200,
        "concurrency_exact": payload.get("concurrency") == 20,
        "logical_users_exact": payload.get("logical_users") == 100,
        "request_count_nonzero": total > 0,
        "request_accounting_exact": success_count + error_count == total,
        "error_rate_at_most_one_percent": total > 0 and error_count / total <= 0.01,
        "timeout_rate_at_most_half_percent": total > 0 and timeout_count / total <= 0.005,
        "permission_bypass_successes_zero": payload.get("security_violation_successes") == 0,
        "worker_errors_zero": not payload.get("worker_errors"),
        "resource_sample_errors_zero": not payload.get("resource_sample_errors"),
        "session_rotation_exercised": int(payload.get("session_rotation_count") or 0) >= 200,
        "workload_source_hash_matches": host.get("workload_source_sha256") == source_sha256,
        "workload_exit_zero": host.get("workload_exit_code") == 0,
        "all_required_services_sampled": set(resources) == REQUIRED_SERVICES,
        "unexpected_restarts_zero": host.get("unexpected_restart_count") == 0
        and all(not item.get("unexpected") for item in restarts.values()),
        "connection_pool_exhaustion_zero": host.get("connection_pool_exhaustion_count") == 0,
        "sustained_unexplained_growth_zero": all(
            not item.get("sustained_unexplained_growth_detected") for item in resources.values()
        ),
        "audit_loss_zero": invariants.get("audit_loss_detected") is False,
        "audit_count_monotonic": int(invariants.get("audit_final_count") or 0)
        >= int(invariants.get("audit_initial_count") or 0),
        "sqlbot_failure_primary_impact_zero": invariants.get(
            "sqlbot_failure_impacted_primary_answers"
        ) == 0,
    }
    result = {
        "evidence_type": "p5a_capacity_independent_verification",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "verified_at": datetime.now(UTC).isoformat(),
        "source_evidence": args.input.resolve().relative_to(ROOT).as_posix(),
        "source_evidence_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "workload_source_sha256": source_sha256,
        "run_id": payload.get("run_id"),
        "configured_duration_seconds": payload.get("configured_duration_seconds"),
        "actual_duration_seconds": host.get("actual_duration_seconds"),
        "logical_users": payload.get("logical_users"),
        "concurrency": payload.get("concurrency"),
        "total_requests": total,
        "success_count": success_count,
        "error_count": error_count,
        "timeout_count": timeout_count,
        "error_rate": error_count / total if total else 1.0,
        "timeout_rate": timeout_count / total if total else 1.0,
        "p50_ms": payload.get("p50_ms"),
        "p95_ms": payload.get("p95_ms"),
        "p99_ms": payload.get("p99_ms"),
        "session_rotation_count": payload.get("session_rotation_count"),
        "checks": checks,
        "production_capacity_verified": False,
        "production_release_authorized": False,
        "production_traffic_switched": False,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rendered.encode("utf-8"))
    print(json.dumps({
        "status": result["status"], "run_id": result["run_id"],
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "evidence_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    }, sort_keys=True))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
