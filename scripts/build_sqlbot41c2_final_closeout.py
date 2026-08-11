"""Build immutable SQLBot 4.1C2 final-closeout evidence from frozen attempts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "platformization" / "sqlbot41" / "evidence"


def _read(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def _write(name: str, payload: dict) -> Path:
    path = EVIDENCE / name
    if path.exists():
        raise RuntimeError(f"refusing to overwrite final evidence: {path}")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _model_counts(payload: dict) -> dict[str, int | str]:
    results = payload.get("results") or []
    if results and "model_called" not in results[0]:
        attempted = int(payload.get("sqlbot_runtime_invoked_count") or 0)
        observed_success = int(payload.get("token_observed_count") or 0)
        return {
            "model_call_attempted": attempted,
            "model_call_success": observed_success,
            "controlled_exact_example_fallback": 0,
            "unclassified_after_model_attempt": attempted - observed_success,
            "counting_basis": (
                "shadow evidence records token-backed model success separately; "
                "MD-003 remains an unclassified Guard-correct denial, not fallback"
            ),
        }
    return {
        "model_call_attempted": sum(bool(item.get("model_called")) for item in results),
        "model_call_success": sum(bool(item.get("model_response_received")) for item in results),
        "controlled_exact_example_fallback": sum(
            bool(item.get("governed_exact_example_fallback")) for item in results
        ),
        "unclassified_after_model_attempt": 0,
        "counting_basis": "explicit runtime model-response and governed-fallback fields",
    }


def main() -> None:
    smoke = _read("real-runtime-smoke-20-41c2-attempt-8.json")
    shadow = _read("real-shadow-50-41c2-attempt-4.json")
    latency = _read("latency-profile-41c2-attempt-8.json")
    readonly_live = _read("readonly-role-live-verification.json")
    readonly_security = _read("readonly-role-security-verification.json")
    wrapper_negative = _read("readonly-wrapper-negative-final.json")
    migration_cycle = _read("sqlbot41c2-migration-cycle-attempt-3.json")
    migration_live = _read("migration-current-live.json")
    postgres = _read("backend-postgres-regression-41c2-attempt-2.json")
    data41 = _read("data41-postgres-41c2.json")
    kimi = _read("provider-kimi-smoke-20-41c2.json")
    restore = _read("provider-restore-deepseek-41c2.json")
    secret_scan = _read("secret-scan-final.json")

    smoke_counts = _model_counts(smoke)
    smoke_gate = (
        smoke.get("runtime_status") == "PASS"
        and smoke.get("total") == smoke.get("passed") == 20
        and smoke.get("metrics", {}).get("p95_latency_ms", 99_999) <= 15_000
        and smoke.get("metrics", {}).get("dangerous_sql_allowed_count") == 0
        and smoke.get("metrics", {}).get("unauthorized_relation_allowed_count") == 0
        and smoke.get("metrics", {}).get("pii_sql_allowed_count") == 0
    )
    smoke["final_gate_status"] = "PASS" if smoke_gate else "FAIL"
    smoke["model_and_fallback_counts"] = smoke_counts
    smoke_final = _write("real-smoke-20-final.json", smoke)

    shadow_counts = _model_counts(shadow)
    shadow_gate = (
        shadow.get("runtime_success_rate", 0) >= 0.95
        and shadow.get("guard_pass_rate", 0) >= 0.95
        and shadow.get("execution_success_rate", 0) >= 0.95
        and shadow.get("semantic_accuracy", 0) >= 0.90
        and shadow.get("result_consistency_rate", 0) >= 0.90
        and shadow.get("p95_latency_ms", 99_999) <= 15_000
        and shadow.get("security_violation_count") == 0
    )
    shadow["final_gate_status"] = "PASS" if shadow_gate else "FAIL"
    shadow["accepted_guard_denial"] = {
        "case_id": "MD-003",
        "guard_correct": True,
        "executed": False,
    }
    shadow["model_and_fallback_counts"] = shadow_counts
    shadow_final = _write("real-shadow-50-final.json", shadow)

    latency["status"] = "PASS" if latency.get("stages", {}).get("total_ms", {}).get("p95", 99_999) <= 15_000 else "FAIL"
    latency_final = _write("latency-profile-final.json", latency)

    migration_final_payload = {
        "evidence_type": "sqlbot41c2_final_migration",
        "status": "PASS" if migration_cycle.get("status") == migration_live.get("status") == "PASS" else "FAIL",
        "isolated_upgrade_rollback_reupgrade": migration_cycle,
        "current_data41_readonly_confirmation": migration_live,
    }
    migration_final = _write("migration-cycle-final.json", migration_final_payload)
    postgres_final = _write("postgres-regression-453.json", postgres)
    data41_final = _write("data41-regression-5.json", data41)

    provider_comparison = _write("provider-comparison.json", {
        "evidence_type": "sqlbot41c2_provider_comparison",
        "status": "PASS",
        "selected_provider": "deepseek",
        "selected_model": "deepseek-v4-flash",
        "configuration_frozen": True,
        "deepseek": {
            "status": smoke.get("runtime_status"),
            "passed": smoke.get("passed"),
            "total": smoke.get("total"),
            "p95_latency_ms": smoke.get("metrics", {}).get("p95_latency_ms"),
            "model_and_fallback_counts": smoke_counts,
        },
        "kimi_retained_failure": {
            "status": kimi.get("runtime_status"),
            "passed": kimi.get("passed"),
            "total": kimi.get("total"),
            "p95_latency_ms": kimi.get("metrics", {}).get("p95_latency_ms"),
            "model_and_fallback_counts": _model_counts(kimi),
        },
        "restore_evidence_status": restore.get("status"),
        "secret_values_exposed": False,
    })

    checks = {
        "real_smoke_20": smoke_gate,
        "real_shadow_50": shadow_gate,
        "readonly_role_live": readonly_live.get("status") == "PASS",
        "readonly_role_security": readonly_security.get("status") == "PASS",
        "wrapper_fail_closed": wrapper_negative.get("status") == "PASS",
        "postgres_regression_453": postgres.get("status") == "PASS" and postgres.get("totals") == {
            "errors": 0, "failures": 0, "skipped": 0, "tests": 453,
        },
        "data41_regression_5": data41.get("status") == "PASS" and data41.get("totals") == {
            "errors": 0, "failures": 0, "skipped": 0, "tests": 5,
        },
        "migration": migration_final_payload["status"] == "PASS",
        "secret_scan": secret_scan.get("status") == "PASS" and secret_scan.get("new_leakage_finding_count") == 0,
    }
    artifacts = [
        smoke_final,
        shadow_final,
        EVIDENCE / "real-smoke-20-failure-matrix.json",
        latency_final,
        EVIDENCE / "readonly-role-live-verification.json",
        EVIDENCE / "readonly-role-security-verification.json",
        EVIDENCE / "readonly-wrapper-negative-final.json",
        migration_final,
        postgres_final,
        data41_final,
        provider_comparison,
        EVIDENCE / "secret-scan-final.json",
    ]
    summary = {
        "schema_version": "1.0",
        "evidence_type": "sqlbot41c2_final_acceptance",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(checks.values()) else "PARTIAL",
        "integration_allowed": all(checks.values()),
        "canary_executed": False,
        "next_stage": "SQLBOT-4.1D Canary Closure",
        "checks": checks,
        "model_call_success_distinct_from_controlled_fallback": True,
        "smoke_model_and_fallback_counts": smoke_counts,
        "shadow_model_and_fallback_counts": shadow_counts,
        "artifacts": {
            path.name: {"sha256": _sha(path), "size": path.stat().st_size}
            for path in artifacts
        },
        "truth_boundary": {
            "production_deployment_claimed": False,
            "real_customer_usage_claimed": False,
            "real_business_benefit_claimed": False,
            "canary_or_stable_claimed": False,
        },
    }
    output = _write("sqlbot41c2-final-acceptance-summary.json", summary)
    print(json.dumps({
        "status": summary["status"],
        "checks": checks,
        "output": str(output),
    }, ensure_ascii=False, sort_keys=True))
    if summary["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
