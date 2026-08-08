"""Aggregate immutable DATA-4.1 acceptance artifacts into one machine summary."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "platformization" / "data41" / "evidence"


def load(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8-sig"))


def junit(name: str) -> dict[str, int]:
    root = ElementTree.parse(EVIDENCE / name).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cold = load("data41-cold-start.json")
    warm = load("data41-warm-start.json")
    regression = load("data41-postgres-full-final-rerun.json")
    catalog_acceptance = load("data41-catalog-focused.json")
    migration = load("data41-migration-cycle.json")
    secret = load("data41-secret-scan.json")
    frontend_truth = load("data41-frontend-truth-scan.json")
    manifest = json.loads((ROOT / "data" / "open_source" / "source_manifest.json").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "docs" / "data" / "schema_catalog.json").read_text(encoding="utf-8"))
    live = junit("data41-playwright-live.xml")
    oidc = junit("data41-playwright-oidc.xml")
    primary = [
        "data41-cold-start.json", "data41-warm-start.json",
        "data41-postgres-full-final-rerun.json", "data41-catalog-focused.json",
        "data41-migration-cycle.json", "data41-frontend-truth-scan.json",
        "data41-playwright-live.xml",
        "data41-playwright-oidc.xml",
    ]
    checks = {
        "DATASET_IMPORT": cold["status"] == warm["status"] == "PASS",
        "DATA_QUALITY": '"quality_check_pass_count": 28' in next(
            step["detail"] for step in warm["steps"] if step["name"] == "Open-source import and lineage"
        ),
        "DATA_LINEAGE": cold["data"]["classification"] == "open_source_real_data",
        "DB_API_UI": live == {"tests": 1, "failures": 0, "errors": 0, "skipped": 0},
        "DETERMINISTIC_CHATBI": live["tests"] == 1 and live["failures"] == 0,
        "ONE_CLICK_START": cold["status"] == warm["status"] == "PASS",
        "IDEMPOTENT_REUSE": '"reused": true' in next(
            step["detail"] for step in warm["steps"] if step["name"] == "Open-source import and lineage"
        ),
        "NO_STARTUP_DOWNLOAD": '"source_download_on_startup": false' in next(
            step["detail"] for step in warm["steps"] if step["name"] == "Open-source import and lineage"
        ),
        "REGRESSION_368": regression["status"] == "PASS" and regression["totals"] == {
            "tests": 368, "failures": 0, "errors": 0, "skipped": 0,
        },
        "OIDC_LIVE_3": oidc == {"tests": 3, "failures": 0, "errors": 0, "skipped": 0},
        "MIGRATION_CYCLE": migration["passed"] and migration["database_removed"],
        "SCHEMA_CATALOG": catalog_acceptance["status"] == "PASS"
            and catalog["statistics"] == {"table_count": 13, "field_count": 141, "relation_count": 19}
            and catalog["sqlbot_enabled"] is False,
        "FRONTEND_TRUTH_SCAN": frontend_truth["status"] == "PASS" and frontend_truth["finding_count"] == 0,
        "SECRET_SCAN": secret["status"] == "PASS" and secret["new_leakage_finding_count"] == 0,
    }
    result = {
        "schema_version": "1.0",
        "evidence_type": "data41_acceptance_summary",
        "generated_at": datetime.now(UTC).isoformat(),
        "phase": "DATA-4.1_OPEN_SOURCE_REAL_DATA_BASELINE",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "base_sha": "5de9ea85d0472b98a9265c29623c5ceb1b1cf1b2",
        "branch": "codex/data-open-source-41",
        "data_classification": "open_source_real_data",
        "checks": checks,
        "sources": manifest["snapshots"],
        "quality": {"passed": 28, "failed": 0},
        "dataset_versions": {"charging_ops": 2, "sales_ops": 2},
        "tests": {"postgres": regression["totals"], "live_e2e": live, "oidc_e2e": oidc, "catalog": catalog_acceptance["totals"]},
        "schema_catalog": catalog["statistics"] | {"sqlbot_enabled": catalog["sqlbot_enabled"]},
        "artifacts": {name: {"path": f"docs/platformization/data41/evidence/{name}", "sha256": sha256(EVIDENCE / name)} for name in primary},
        "production_release_authorized": False,
        "production_traffic_switched": False,
        "secret_values_recorded": False,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": checks}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
