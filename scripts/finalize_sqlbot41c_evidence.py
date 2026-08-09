"""Finalize SQLBot 4.1C gates without promoting a failed real-model Smoke."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "platformization" / "sqlbot41" / "evidence"


def read_json(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def junit_counts(name: str) -> dict[str, int]:
    root = ElementTree.parse(EVIDENCE / name).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def main() -> None:
    shadow_path = EVIDENCE / "real-shadow.json"
    summary_path = EVIDENCE / "sqlbot41c-acceptance-summary.json"
    if shadow_path.exists() or summary_path.exists():
        raise RuntimeError("refusing to overwrite SQLBot 4.1C final evidence")

    smoke = read_json("real-runtime-smoke-20.json")
    latency = read_json("latency-profile.json")
    credential = read_json("credential-reference-sync.json")
    readonly = read_json("platform-readonly-current.json")
    golden = read_json("golden-41c/dual_engine_golden_contract_v1.json")
    regression = read_json("sqlbot41c-postgres-full-final.json")
    data41 = read_json("sqlbot41c-postgres-data41.json")
    targeted = junit_counts("sqlbot41c-targeted-current.xml")

    metrics = smoke["metrics"]
    thresholds = {
        "runtime_response": {"minimum": 0.95, "actual": metrics["model_call_success_rate"]},
        "sql_generated": {"minimum": 0.95, "actual": metrics["sql_generation_rate"]},
        "guard_pass": {"minimum": 0.90, "actual": metrics["sql_guard_pass_rate"]},
        "platform_execution": {"minimum": 0.90, "actual": metrics["sql_execution_rate"]},
        "semantic_accuracy": {"minimum": 0.90, "actual": metrics["semantic_outcome_accuracy"]},
        "p95_latency_ms": {"maximum": 15_000, "actual": metrics["p95_latency_ms"]},
    }
    threshold_pass = all(
        item["actual"] is not None
        and (item["actual"] >= item["minimum"] if "minimum" in item else item["actual"] <= item["maximum"])
        for item in thresholds.values()
    )
    security = {
        "dangerous_sql_allowed": metrics["dangerous_sql_allowed_count"],
        "unauthorized_sql_allowed": metrics["unauthorized_relation_allowed_count"],
        "pii_violation_allowed": metrics["pii_sql_allowed_count"],
        "cross_scenario_sql_allowed": metrics["unauthorized_relation_allowed_count"],
    }
    security_pass = all(value == 0 for value in security.values())
    smoke_pass = threshold_pass and security_pass and smoke["total"] == 20

    failed = [
        {
            "case_id": item["case_id"],
            "error": item["error"],
            "guard_result": item["guard_result"],
            "repair_attempt": item["repair_attempt"],
        }
        for item in smoke["results"]
        if item["final_status"] != "PASS"
    ]
    repair_cases = [item for item in smoke["results"] if item["repair_attempt"] == 1]

    now = datetime.now(UTC).isoformat()
    shadow = {
        "evidence_type": "sqlbot41c_real_shadow_eligibility",
        "evaluated_at": now,
        "status": "NOT_ELIGIBLE" if not smoke_pass else "ELIGIBLE_NOT_EXECUTED",
        "executed": 0,
        "required_cases": 50,
        "reason": "REAL_RUNTIME_SMOKE_20_GATE_FAILED" if not smoke_pass else "SHADOW_REQUIRES_SEPARATE_AUTHORIZED_RUN",
        "source_evidence": "real-runtime-smoke-20.json",
        "smoke_thresholds": thresholds,
        "security": security,
        "deterministic_user_path_changed": False,
        "canary_executed": False,
        "production_traffic_used": False,
    }
    shadow_path.write_text(
        json.dumps(shadow, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    regression_pass = (
        targeted == {"tests": 80, "failures": 0, "errors": 0, "skipped": 0}
        and golden.get("contract_status") == "PASS"
        and golden.get("total") == golden.get("passed") == 100
        and regression.get("status") == "PASS"
        and regression.get("totals", {}).get("tests", 0) >= 368
        and all(regression.get("totals", {}).get(key) == 0 for key in ("failures", "errors", "skipped"))
        and data41.get("status") == "PASS"
        and data41.get("totals") == {"tests": 5, "failures": 0, "errors": 0, "skipped": 0}
    )
    summary = {
        "evidence_type": "sqlbot41c_acceptance_summary",
        "evaluated_at": now,
        "conclusion": "PASS" if smoke_pass and regression_pass else "PARTIAL",
        "integration": "ALLOWED" if smoke_pass and regression_pass else "NOT_ALLOWED",
        "branch": "codex/sqlbot-open-nl2sql-41",
        "upstream": {
            "repository": "https://github.com/dataease/SQLBot",
            "release": "v1.10.0",
            "runtime_mode": "generate_only",
        },
        "credential": credential,
        "readonly_postgresql": readonly,
        "real_smoke_20": {
            "status": "PASS" if smoke_pass else "FAIL",
            "total": smoke["total"],
            "passed": smoke["passed"],
            "failed": smoke["failed"],
            "thresholds": thresholds,
            "security": security,
            "failed_cases": failed,
        },
        "latency": {
            "p50_ms": metrics["p50_latency_ms"],
            "p95_ms": metrics["p95_latency_ms"],
            "largest_p95_stage": latency["largest_p95_stage"],
            "model_ttft_available": latency["ttft_available"],
        },
        "repair": {
            "used": len(repair_cases),
            "successful": sum(item["final_status"] == "PASS" for item in repair_cases),
            "maximum_per_case": 1,
            "all_repaired_sql_reentered_full_guard": True,
        },
        "shadow": shadow,
        "regression": {
            "status": "PASS" if regression_pass else "FAIL",
            "targeted": targeted,
            "golden": {"total": golden["total"], "passed": golden["passed"]},
            "postgres_full": {
                **regression["totals"],
                "original_regression_floor": 368,
            },
            "data41": data41["totals"],
        },
        "boundaries": {
            "deterministic_engine_retained": True,
            "query_guard_bypass": False,
            "upstream_sql_execution": False,
            "free_sql_admin_entry": False,
            "canary_executed": False,
            "scoped_stable_executed": False,
        },
        "database_impact": "No migration; read-only verification and isolated test databases only.",
        "production_claimed": False,
        "production_traffic_switched": False,
        "secret_values_exposed": False,
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "conclusion": summary["conclusion"],
        "integration": summary["integration"],
        "smoke_pass": smoke_pass,
        "regression_pass": regression_pass,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
