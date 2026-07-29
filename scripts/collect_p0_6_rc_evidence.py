"""Collect machine-readable V2-P0.6 release-candidate acceptance evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_gate(name: str, command: list[str]) -> dict:
    started = time.monotonic()
    process = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {
        "name": name,
        "exit_code": process.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "passed": process.returncode == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=ROOT / "docs" / "v2" / "evidence" / "p0_6",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence_dir = args.evidence_dir.resolve()
    output = (args.output or evidence_dir / "rc-acceptance.json").resolve()

    suite = ET.parse(evidence_dir / "backend.xml").getroot().find("testsuite")
    if suite is None:
        raise RuntimeError("backend JUnit testsuite missing")
    backend = {
        "tests": int(suite.attrib["tests"]),
        "failures": int(suite.attrib["failures"]),
        "errors": int(suite.attrib["errors"]),
        "skipped": int(suite.attrib["skipped"]),
        "duration_seconds": float(suite.attrib["time"]),
    }
    backend["passed"] = (
        backend["tests"] > 0
        and backend["failures"] == 0
        and backend["errors"] == 0
        and backend["skipped"] == 0
    )

    e2e_raw = read_json(evidence_dir / "e2e.json")
    e2e_stats = e2e_raw["stats"]
    e2e = {
        "tests": e2e_stats["expected"],
        "unexpected": e2e_stats["unexpected"],
        "flaky": e2e_stats["flaky"],
        "skipped": e2e_stats["skipped"],
        "duration_seconds": round(e2e_stats["duration"] / 1000, 3),
        "passed": (
            e2e_stats["expected"] > 0
            and e2e_stats["unexpected"] == 0
            and e2e_stats["flaky"] == 0
            and e2e_stats["skipped"] == 0
        ),
    }

    chatbi = read_json(ROOT / "tests" / "evaluation" / "output" / "chatbi_eval_v0.1.json")
    smoke = read_json(ROOT / "tests" / "evaluation" / "output" / "docker_smoke.json")
    phase_gates = {
        "preflight": read_json(evidence_dir / "preflight.json"),
        "cold_install": read_json(evidence_dir / "cold-install.json"),
        "backup": read_json(evidence_dir / "backup.json"),
        "restore_drill": read_json(evidence_dir / "restore-drill.json"),
        "monitor": read_json(evidence_dir / "monitor.json"),
        "migration_rollback": read_json(evidence_dir / "migration-rollback.json"),
    }
    phase_statuses = {
        name: value.get("status", "passed" if value.get("passed") else "failed")
        for name, value in phase_gates.items()
    }

    command_gates = [
        run_gate(
            "frontend_vitest",
            ["npm.cmd", "test", "--prefix", "frontend"],
        ),
        run_gate(
            "frontend_build",
            ["npm.cmd", "run", "build", "--prefix", "frontend"],
        ),
        run_gate(
            "python_compile",
            [
                str(ROOT / ".venv" / "Scripts" / "python.exe"),
                "-m",
                "compileall",
                "-q",
                "backend/app",
                "scripts",
            ],
        ),
    ]
    audit_process = subprocess.run(
        ["npm.cmd", "audit", "--prefix", "frontend", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    audit_payload = json.loads(audit_process.stdout)
    vulnerabilities = audit_payload.get("metadata", {}).get("vulnerabilities", {})
    command_gates.append(
        {
            "name": "npm_audit",
            "exit_code": audit_process.returncode,
            "known_vulnerabilities": vulnerabilities.get("total", 0),
            "passed": audit_process.returncode == 0 and vulnerabilities.get("total", 0) == 0,
        }
    )

    phase_passed = all(status in {"passed", "completed"} for status in phase_statuses.values())
    passed = all([
        backend["passed"],
        e2e["passed"],
        chatbi["total"] == 40 and chatbi["failed"] == 0,
        smoke["passed"],
        phase_passed,
        all(gate["passed"] for gate in command_gates),
    ])
    result = {
        "stage": "V2-P0.6",
        "release_version": "0.6.0-rc1",
        "collected_at": datetime.now(UTC).isoformat(),
        "status": "passed" if passed else "failed",
        "data_classification": "simulated",
        "deployment_scope": "single_customer_single_host_docker_compose",
        "backend": backend,
        "frontend_e2e": e2e,
        "chatbi_fixed_evaluation": {
            "tests": chatbi["total"],
            "passed": chatbi["passed"],
            "failed": chatbi["failed"],
        },
        "docker_smoke": smoke,
        "phase_gate_statuses": phase_statuses,
        "command_gates": command_gates,
        "restore_reconciliation": {
            "tables": phase_gates["restore_drill"]["table_count"],
            "rows": phase_gates["restore_drill"]["row_count_total"],
            "table_counts_match": phase_gates["restore_drill"]["table_counts_match"],
            "business_fingerprint_match": phase_gates["restore_drill"]["business_fingerprint_match"],
            "schema_removed": phase_gates["restore_drill"]["schema_removed"],
        },
        "truth_boundary": {
            "production_deployed": False,
            "real_customer_validated": False,
            "real_enterprise_data_used": False,
            "high_availability_validated": False,
            "shared_multitenancy_validated": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
