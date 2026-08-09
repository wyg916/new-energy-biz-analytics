"""Build the SQLBot 4.1B machine-readable closeout from tracked evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_dir
    golden_path = evidence / "sqlbot41b-golden-contract-100.json"
    smoke_path = evidence / "sqlbot41b-live-smoke-env-acceptance.json"
    regression_path = evidence / "sqlbot41b-postgres-full-final.json"
    targeted_path = evidence / "sqlbot41b-targeted-current.xml"
    inputs = (golden_path, smoke_path, regression_path, targeted_path)
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing closeout evidence: {missing}")

    golden = _json(golden_path)
    smoke = _json(smoke_path)
    regression = _json(regression_path)
    suite = ElementTree.parse(targeted_path).getroot().find("testsuite")
    if suite is None:
        raise RuntimeError("targeted JUnit has no testsuite")
    targeted = {
        key: int(suite.attrib.get(key, "0"))
        for key in ("tests", "failures", "errors", "skipped")
    }
    if golden.get("contract_status") != "PASS" or golden.get("total") != 100:
        raise RuntimeError("Golden contract is not 100-case PASS")
    if regression.get("status") != "PASS" or regression.get("totals", {}).get("tests") != 368:
        raise RuntimeError("corrected 368-test PostgreSQL regression is not PASS")
    if any(targeted[key] for key in ("failures", "errors", "skipped")):
        raise RuntimeError("targeted SQLBot tests are not clean")

    generated = int(round(smoke["metrics"]["sql_generation_rate"] * smoke["total"]))
    result = {
        "evidence_type": "sqlbot_41b_closeout",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PARTIAL",
        "integration_allowed": False,
        "data_classification": "simulated_and_open_source_real_data",
        "tests": {
            "targeted": {"status": "PASS", **targeted},
            "offline_golden": {
                "status": "PASS",
                "tests": golden["total"],
                "passed": golden["passed"],
                "dangerous_sql_successes": golden["dangerous_sql_successes"],
                "permission_attack_successes": golden["permission_attack_successes"],
            },
            "postgresql_regression": {"status": regression["status"], **regression["totals"]},
            "live_runtime_smoke": {
                "status": "FAIL",
                "tests": smoke["total"],
                "passed": smoke["passed"],
                "failed": smoke["failed"],
                "sql_generated": generated,
                "guard_passed": 0,
                "platform_queries_executed": 0,
                "permission_violations": 0,
                "cross_scenario_violations": 0,
                "upstream_sql_execution": False,
                "credential_source": smoke["credential_source"],
            },
        },
        "rollout": {
            "shadow": "NOT_ELIGIBLE",
            "canary_5_percent": "NOT_EXECUTED",
            "canary_20_percent": "NOT_EXECUTED",
            "scoped_stable": "NOT_EXECUTED",
            "automatic_fallback": "PASS_CONTRACT_ONLY",
            "promotion_blockers": [
                "live runtime smoke is 0/10",
                "CredentialReference authentication does not match the SQLBot runtime account",
                "no successful Guard-to-platform-readonly live query exists after schema normalization",
            ],
        },
        "boundaries": {
            "sqlbot_endpoint": "generate-only /api/v1/mcp/mcp_generate_sql",
            "sqlbot_executes_sql": False,
            "platform_query_guard_required": True,
            "scenario_readonly_role_required": True,
            "missing_scenario_connection": "fail_closed",
            "free_sql_admin_entry": False,
            "deterministic_engine_preserved": True,
        },
        "inputs": {
            path.name: {"sha256": _sha256(path)} for path in inputs
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": result["status"], "integration_allowed": False}))


if __name__ == "__main__":
    main()
