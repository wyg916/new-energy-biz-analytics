"""Validate SQLBot 4.1 evidence and emit a checksum manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _junit(path: Path) -> dict[str, int]:
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    required = {
        "acceptance": evidence / "acceptance-summary.json",
        "regression": evidence / "backend-postgres-regression-final.json",
        "targeted": evidence / "sqlbot41-targeted.xml",
        "golden": evidence / "dual_engine_golden_contract_v1.json",
        "data41": evidence / "data41-postgres-rerun.json",
        "live_data": evidence / "live-data41-postgres.json",
        "runtime_gate": evidence / "sqlbot-runtime-gate.json",
        "secret_scan": evidence / "secret-scan.json",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing SQLBot 4.1 evidence: {missing}")

    regression = _json(required["regression"])
    targeted = _junit(required["targeted"])
    golden = _json(required["golden"])
    data41 = _json(required["data41"])
    live_data = _json(required["live_data"])
    runtime = _json(required["runtime_gate"])
    secret_scan = _json(required["secret_scan"])
    checks = {
        "postgres_regression_368": regression.get("status") == "PASS"
        and regression.get("totals") == {
            "tests": 368, "failures": 0, "errors": 0, "skipped": 0
        },
        "targeted_75": targeted == {
            "tests": 75, "failures": 0, "errors": 0, "skipped": 0
        },
        "golden_100": golden.get("contract_status") == "PASS"
        and golden.get("total") == golden.get("passed") == 100,
        "data41_postgres_5": data41.get("status") == "PASS"
        and data41.get("totals", {}).get("tests") == 5,
        "live_data_readonly": live_data.get("status") == "PASS"
        and live_data.get("transaction_read_only") is True
        and live_data.get("transaction_rolled_back") is True,
        "runtime_truthful_block": runtime.get("status") == "BLOCKED"
        and runtime.get("mock_used_as_live_evidence") is False,
        "secret_scan": secret_scan.get("status") == "PASS"
        and secret_scan.get("new_leakage_finding_count") == 0,
    }
    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PARTIAL" if all(checks.values()) else "FAIL",
        "checks": checks,
        "artifacts": {
            name: {
                "path": path.relative_to(evidence.parent.parent.parent.parent).as_posix(),
                "sha256": _sha(path),
            }
            for name, path in required.items()
        },
        "truth_boundary": {
            "implementation_and_contract_tests": "PASS" if all(checks.values()) else "FAIL",
            "real_sqlbot_runtime": "BLOCKED",
            "real_canary_claimed": False,
            "production_promotion_authorized": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": manifest["status"], "checks": checks}))
    raise SystemExit(0 if manifest["status"] == "PARTIAL" else 1)


if __name__ == "__main__":
    main()
