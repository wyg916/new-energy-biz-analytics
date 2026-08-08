"""Validate P5C evidence and write the machine-readable acceptance summary."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "platformization" / "p5c" / "evidence"
OUTPUT = EVIDENCE / "p5c-acceptance-summary.json"


def read_json(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def junit_counts(name: str) -> dict[str, int]:
    root = ElementTree.parse(EVIDENCE / name).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    return {
        key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def git(*args: str) -> str:
    process = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
    )
    if process.returncode:
        raise RuntimeError(f"git command failed safely: {args[:2]}")
    return process.stdout.strip()


def main() -> None:
    baseline = read_json("p5c-baseline-adjudication.json")
    secret_scan = read_json("p5c-secret-scan.json")
    backend = read_json("p5c-backend-regression.json")
    vitest = read_json("p5c-vitest.json")
    startup_attempt_1 = read_json("p5c-startup-report-attempt-1.json")
    startup_attempt_2 = read_json("p5c-startup-report-attempt-2.json")
    startup = read_json("p5c-startup-report.json")
    playwright = junit_counts("p5c-playwright-live.xml")
    playwright_attempt_1 = junit_counts("p5c-playwright-live-attempt-1.xml")
    build_text = (EVIDENCE / "p5c-frontend-build.txt").read_text(encoding="utf-8")

    checks = {
        "baseline_adjudication": baseline.get("status") == "PASS",
        "secret_scan": secret_scan.get("status") == "PASS" and secret_scan.get("new_leakage_finding_count") == 0,
        "backend_regression_363": backend.get("status") == "PASS" and backend.get("totals") == {
            "tests": 363, "failures": 0, "errors": 0, "skipped": 0,
        },
        "backend_temporary_resources_removed": backend.get("temporary_containers_removed") is True,
        "vitest_3": vitest.get("success") is True and vitest.get("numPassedTests") == vitest.get("numTotalTests") == 3,
        "typescript_vite_build": "built in" in build_text and "49 modules transformed" in build_text,
        "live_oidc_and_gate_e2e_4": playwright == {"tests": 4, "failures": 0, "errors": 0, "skipped": 0},
        "cold_start": startup.get("status") == "PASS" and all(
            step.get("status") == "PASS" for step in startup.get("steps", [])
        ),
        "migration_head": startup.get("runtime", {}).get("expected_migration_head") == "p5_0001",
        "release_version": startup.get("runtime", {}).get("release_version") == "4.0.0-rc.3",
        "production_not_authorized": startup.get("runtime", {}).get("production_release_authorized") is False,
        "failed_attempts_preserved": (
            startup_attempt_1.get("status") == "FAIL"
            and startup_attempt_2.get("status") == "FAIL"
            and playwright_attempt_1 == {"tests": 4, "failures": 4, "errors": 0, "skipped": 0}
        ),
        "control_branch": git("branch", "--show-current") == "codex/p5c-baseline-convergence",
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    artifacts = [
        "p5c-baseline-adjudication.json",
        "p5c-secret-scan.json",
        "p5c-backend-regression.json",
        "p5c-vitest.json",
        "p5c-frontend-build.txt",
        "p5c-playwright-live-attempt-1.xml",
        "p5c-playwright-live.xml",
        "p5c-startup-report-attempt-1.json",
        "p5c-startup-report-attempt-2.json",
        "p5c-startup-report.json",
    ]
    payload = {
        "schema_version": "1.0",
        "evidence_type": "p5c_acceptance_summary",
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "phase": "P5C_FACT_SECURITY_RELEASE_TRUTH_CONVERGENCE",
        "git": {
            "worktree": str(ROOT),
            "branch": git("branch", "--show-current"),
            "start_sha": "6ee3ccc9e893960f11d4a147d676de1ba0b00e6f",
            "head_at_acceptance": git("rev-parse", "HEAD"),
            "commit_binding": "THIS_SUMMARY_IS_VALID_ONLY_INSIDE_THE_P5C_STAGE_COMMIT",
        },
        "release_truth": {
            "runtime_release": "4.0.0-rc.3",
            "migration_head": "p5_0001",
            "next_release_stream": "4.1.0",
            "next_release_status": "PLANNED_NOT_YET_RC",
            "production_release_authorized": False,
            "production_traffic_switched": False,
        },
        "data": {
            "classification": "simulated",
            "period_start": "2025-01-01",
            "period_end": "2026-06-30",
            "source": "fixed-seed business-rule simulation stored in PostgreSQL",
            "run_id_location": "API responses and audit/evidence records",
        },
        "tests": {
            "secret_scan": {
                "status": secret_scan.get("status"),
                "new_leakage_findings": secret_scan.get("new_leakage_finding_count"),
            },
            "backend": backend.get("totals"),
            "vitest": {"passed": vitest.get("numPassedTests"), "total": vitest.get("numTotalTests")},
            "typescript_vite": "PASS",
            "playwright_live": playwright,
            "cold_start": {"status": startup.get("status"), "steps": len(startup.get("steps", []))},
        },
        "preserved_failures": {
            "startup_attempt_1": "missing mutable tag alias in inventory check",
            "startup_attempt_2": "Windows PowerShell native stderr handling",
            "playwright_attempt_1": "container-to-host port mapping",
            "product_assertion_failures": 0,
        },
        "checks": checks,
        "artifacts": {
            name: {"path": f"docs/platformization/p5c/evidence/{name}", "sha256": sha256(EVIDENCE / name)}
            for name in artifacts
        },
        "database_schema_changed": False,
        "main_database_destructively_modified": False,
        "secret_values_recorded": False,
        "known_limits": [
            "Git HTTPS CLI live verification failed twice with connection reset; GitHub branch page and local tracking evidence were used read-only.",
            "The owner-supplied DOCX could not be rendered because LibreOffice is unavailable; structured paragraphs and all 46 tables were read.",
            "Remote branch was not pushed and no RC tag was created in P5C.",
            "P5B production gates remain open or blocked; P5C does not authorize production or implement 4.1 features.",
        ],
        "next_allowed_action": "COMMIT_P5C_THEN_START_DATA_OR_MUTUALLY_EXCLUSIVE_WORKTREES_FROM_THE_SAME_SHA",
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(json.dumps({"status": status, "checks": checks}, sort_keys=True))
    raise SystemExit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()
