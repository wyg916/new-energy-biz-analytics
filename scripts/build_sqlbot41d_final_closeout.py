"""Validate SQLBot 4.1D rollout evidence and build the final manifest."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "platformization" / "sqlbot41" / "evidence"
OUTPUT = EVIDENCE / "sqlbot41d-final-acceptance-summary.json"


def _read(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8-sig"))


def _junit(name: str) -> dict[str, int]:
    root = ElementTree.parse(EVIDENCE / name).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction + 0.9999) - 1))
    return ordered[index]


def _metrics_with_p50(payload: dict, routes: dict) -> dict:
    metrics = dict(payload.get("metrics") or {})
    metrics.setdefault("p50_latency_ms", _percentile([
        int(event["latency_ms"])
        for event in routes.get("events", [])
        if event.get("sqlbot_attempted") and event.get("latency_ms") is not None
    ], 0.50))
    return metrics


def _stage_gate(payload: dict, expected_requests: int) -> bool:
    metrics = payload.get("metrics") or {}
    return all((
        payload.get("status") == "PASS",
        metrics.get("request_count") == expected_requests,
        metrics.get("runtime_availability_rate", 0) >= 0.95,
        metrics.get("guard_pass_rate", 0) >= 0.95,
        metrics.get("execution_success_rate", 0) >= 0.95,
        metrics.get("semantic_accuracy", 0) >= 0.90,
        metrics.get("result_consistency_rate", 0) >= 0.90,
        metrics.get("p95_latency_ms", 99_999) <= 15_000,
        metrics.get("fallback_rate", 1) <= 0.05,
        metrics.get("fallback_final_answer_success_rate", 0) == 1.0,
        metrics.get("permission_violation_count") == 0,
        metrics.get("pii_violation_count") == 0,
        metrics.get("readonly_violation_count") == 0,
        metrics.get("unguarded_sql_count") == 0,
    ))


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing to overwrite final evidence: {OUTPUT}")
    required = {
        name: EVIDENCE / name
        for name in (
            "canary-5-route-events.json",
            "canary-5-acceptance.json",
            "canary-5-fault-injection.json",
            "canary-20-route-events.json",
            "canary-20-acceptance.json",
            "canary-20-stability.json",
            "scoped-stable-route-events.json",
            "scoped-stable-acceptance.json",
            "emergency-fallback.json",
            "one-click-start.json",
            "cold-start.json",
            "migration-current-live-41d.json",
            "real-smoke-20-final.json",
            "real-shadow-50-final.json",
            "postgres-regression-453.json",
            "data41-regression-5.json",
            "postgres-regression-41d.json",
            "data41-regression-41d.json",
            "sqlbot41d-focused.xml",
            "golden-41d/dual_engine_golden_contract_v1.json",
            "platform-readonly-current-41d.json",
            "readonly-wrapper-negative-41d.json",
            "secret-scan-41d.json",
        )
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing SQLBot 4.1D evidence: {missing}")

    canary5 = _read("canary-5-acceptance.json")
    canary20 = _read("canary-20-acceptance.json")
    stable = _read("canary-20-stability.json")
    scoped = _read("scoped-stable-acceptance.json")
    faults = _read("canary-5-fault-injection.json")
    emergency = _read("emergency-fallback.json")
    one_click = _read("one-click-start.json")
    cold_start = _read("cold-start.json")
    migration = _read("migration-current-live-41d.json")
    smoke = _read("real-smoke-20-final.json")
    shadow = _read("real-shadow-50-final.json")
    frozen_postgres = _read("postgres-regression-453.json")
    frozen_data41 = _read("data41-regression-5.json")
    current_postgres = _read("postgres-regression-41d.json")
    current_data41 = _read("data41-regression-41d.json")
    golden = _read("golden-41d/dual_engine_golden_contract_v1.json")
    readonly = _read("platform-readonly-current-41d.json")
    readonly_negative = _read("readonly-wrapper-negative-41d.json")
    secret_scan = _read("secret-scan-41d.json")
    focused = _junit("sqlbot41d-focused.xml")
    route5 = _read("canary-5-route-events.json")
    route20 = _read("canary-20-route-events.json")
    scoped_routes = _read("scoped-stable-route-events.json")
    audit_fields = {
        "request_id", "run_id", "user", "tenant", "workspace", "scenario",
        "route_decision", "canary_percentage", "selected_engine",
        "runtime_status", "model_call_status", "controlled_exact_example_fallback",
        "configured_canary_percentage", "engine_selected",
        "controlled_example_fallback_used", "deterministic_fallback_used",
        "query_guard_result", "answer_guard_result",
        "sql_hash", "guard", "execution", "semantic", "latency_ms",
        "fallback_reason", "answer_guard", "final_engine", "primary_engine",
        "fallback_engine", "sqlbot_failure_stage", "circuit_breaker_state",
    }
    audit_events = (
        route5.get("events", [])
        + route20.get("events", [])
        + scoped_routes.get("events", [])
    )
    checks = {
        "canary_5": _stage_gate(canary5, 100)
        and canary5["metrics"].get("cohort_selected_count") == 5,
        "fault_injection": faults.get("status") == "PASS"
        and faults.get("fault_count") == 10
        and faults.get("automatic_fallback_success_rate") == 1.0,
        "canary_20": _stage_gate(canary20, 200)
        and canary20["metrics"].get("cohort_selected_count") == 40,
        "canary_20_stability": stable.get("status") == "PASS"
        and stable.get("observed_elapsed_seconds", 0) >= 1800
        and all((stable.get("checks") or {}).values()),
        "scoped_stable": _stage_gate(scoped, 40)
        and scoped["metrics"].get("core_deterministic_count", 0) > 0
        and scoped["metrics"].get("high_risk_governed_count", 0) > 0
        and scoped["metrics"].get("scoped_stable_sqlbot_count", 0) > 0,
        "emergency_fallback": emergency.get("status") == "PASS"
        and emergency.get("new_request_deterministic_rate") == 1.0,
        "one_click_start": one_click.get("status") == "PASS"
        and one_click.get("sqlbot_runtime_healthy") is True
        and one_click.get("api_ready") is True
        and all((one_click.get("checks") or {}).values()),
        "cold_start": cold_start.get("status") == "PASS"
        and cold_start.get("sqlbot_runtime_healthy") is True
        and cold_start.get("api_ready") is True
        and all((cold_start.get("checks") or {}).values())
        and (cold_start.get("cold_start") or {}).get("status") == "PASS"
        and (cold_start.get("cold_start") or {}).get(
            "business_data_snapshot_preserved"
        ) is True,
        "migration": migration.get("status") == "PASS"
        and migration.get("alembic_heads") == ["sqlbot_41c2"]
        and all((migration.get("checks") or {}).values()),
        "audit_contract": bool(audit_events)
        and all(audit_fields <= set(event) for event in audit_events),
        "frozen_smoke_20": smoke.get("final_gate_status") == "PASS"
        and smoke.get("total") == smoke.get("passed") == 20,
        "frozen_shadow_50": shadow.get("final_gate_status") == "PASS"
        and shadow.get("total") == 50,
        "frozen_postgres_453": frozen_postgres.get("status") == "PASS"
        and frozen_postgres.get("totals") == {
            "tests": 453, "failures": 0, "errors": 0, "skipped": 0,
        },
        "frozen_data41_5": frozen_data41.get("status") == "PASS"
        and frozen_data41.get("totals") == {
            "tests": 5, "failures": 0, "errors": 0, "skipped": 0,
        },
        "current_postgres_regression": current_postgres.get("status") == "PASS"
        and current_postgres.get("totals", {}).get("tests", 0) >= 453
        and not any(current_postgres.get("totals", {}).get(key) for key in (
            "failures", "errors", "skipped"
        )),
        "current_data41_5": current_data41.get("status") == "PASS"
        and current_data41.get("totals") == {
            "tests": 5, "failures": 0, "errors": 0, "skipped": 0,
        },
        "focused_122": focused["tests"] >= 122
        and focused["failures"] == focused["errors"] == focused["skipped"] == 0,
        "golden_100": golden.get("contract_status") == "PASS"
        and golden.get("total") == golden.get("passed") == 100,
        "readonly_live": readonly.get("status") == "PASS",
        "readonly_fail_closed": readonly_negative.get("status") == "PASS",
        "secret_scan": secret_scan.get("status") == "PASS"
        and secret_scan.get("new_leakage_finding_count") == 0,
    }
    passed = all(checks.values())
    summary = {
        "schema_version": "1.0",
        "evidence_type": "sqlbot41d_final_acceptance",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if passed else "FAIL",
        "full_integration_allowed": passed,
        "checks": checks,
        "canary_5_metrics": _metrics_with_p50(canary5, route5),
        "canary_20_metrics": _metrics_with_p50(canary20, route20),
        "stability_metrics": {
            key: stable.get(key) for key in (
                "observed_elapsed_seconds", "sample_count", "request_count",
                "sqlbot_attempt_count", "fallback_rate",
                "controlled_example_fallback_rate",
                "deterministic_fallback_rate", "real_model_success_rate",
                "fallback_final_answer_success_rate",
                "api_5xx_error_rate", "guard_pass_rate", "guard_reject_rate",
                "execution_success_rate", "timeout_rate",
                "p50_sqlbot_api_latency_ms", "p95_sqlbot_api_latency_ms",
                "runtime_health_rate",
                "max_database_connections",
            )
        },
        "startup": {
            "one_click": {
                "status": one_click.get("status"),
                "mode": (one_click.get("canary_configuration") or {}).get(
                    "startup_mode"
                ),
            },
            "cold_start": {
                "status": cold_start.get("status"),
                "business_data_snapshot_preserved": (
                    cold_start.get("cold_start") or {}
                ).get("business_data_snapshot_preserved"),
            },
        },
        "migration": {
            "status": migration.get("status"),
            "alembic_heads": migration.get("alembic_heads"),
            "business_schema_changed_in_41d": False,
        },
        "scoped_stable_metrics": _metrics_with_p50(scoped, scoped_routes),
        "regression_counts": {
            "frozen_postgres": frozen_postgres["totals"],
            "current_postgres": current_postgres["totals"],
            "data41": current_data41["totals"],
            "focused": focused,
            "golden": {"tests": golden.get("total"), "passed": golden.get("passed")},
        },
        "open_nl2sql_boundary": {
            "scope": "tenant+workspace+user+scenario allowlists are all required",
            "eligible_queries": "registered-schema low/medium-risk exploration only",
            "deterministic_pinned": [
                "core financial metrics", "PII", "system governance",
                "unpublished schema", "unknown joins", "incomplete permission context",
                "unrecognized scenarios", "very-high-cost queries", "Query Guard high risk",
            ],
            "free_sql_admin_entry": False,
            "guard_or_readonly_bypass": False,
        },
        "database_impact": {
            "business_schema_migration": False,
            "business_data_mutation": False,
            "existing_acceptance_audit_records_appended": True,
            "data_classification": "simulated/open-source-derived DATA-4.1 acceptance data",
        },
        "artifacts": {
            name: {"sha256": _sha(path), "size": path.stat().st_size}
            for name, path in required.items()
        },
        "truth_boundary": {
            "production_traffic_claimed": False,
            "real_customer_usage_claimed": False,
            "real_business_benefit_claimed": False,
        },
        "rollback": {
            "immediate": "set SQLBOT_ENGINE_ENABLED=false or QUERY_ENGINE_MODE=DETERMINISTIC_ONLY",
            "code": "git revert the SQLBot 4.1D commit",
            "database": "no business migration or business-data rollback required",
        },
    }
    OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": summary["status"], "checks": checks}, sort_keys=True))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
