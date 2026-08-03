"""Run P5A remediation tests in an isolated PostgreSQL database without printing secrets."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
API_CONTAINER = "renewable-p5a-remediation-api-1"
IMAGE = "renewable-p5a-api:5.0.0-p5a"
NETWORK = "renewable-p5a-remediation-network"
RUNTIME_VOLUME = "renewable-p5a-remediation_p4_runtime"
MANAGER_SOURCE = ROOT / "scripts" / "manage_p5a_test_database.py"
MANAGER_TARGET = "/tmp/manage_p5a_test_database.py"


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.run(list(args), cwd=ROOT, capture_output=True)
    if check and process.returncode:
        raise RuntimeError(f"targeted test command failed safely: {args[:3]}")
    return process


def manage(action: str, database: str) -> None:
    command(
        "docker", "exec", API_CONTAINER,
        "python", "scripts/p4_entrypoint.py",
        "python", MANAGER_TARGET, action, database,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--junit-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args()
    if args.junit_output.exists() or args.summary_output.exists():
        raise RuntimeError("refusing to overwrite targeted test evidence")
    started_at = datetime.now(UTC)
    container = f"renewable-p5a-targeted-tests-{started_at.strftime('%Y%m%d%H%M%S')}"
    command("docker", "cp", str(MANAGER_SOURCE), f"{API_CONTAINER}:{MANAGER_TARGET}")
    database_created = False
    database_removed = False
    test_process: subprocess.CompletedProcess[bytes] | None = None
    junit_copied = False
    try:
        manage("create", args.database)
        database_created = True
        command(
            "docker", "create", "--name", container,
            "--network", NETWORK,
            "-v", f"{RUNTIME_VOLUME}:/run/p4-runtime:ro",
            "-e", "APP_ENV=test",
            "-e", "AUTO_BOOTSTRAP_DEMO_USERS=true",
            "-e", "ACCEPTANCE_POSTGRES_HOST=db",
            "-e", f"ACCEPTANCE_POSTGRES_DB={args.database}",
            "-e", "ACCEPTANCE_TEST_DATABASE_URL_FROM_RUNTIME=true",
            "-w", "/app",
            IMAGE,
            "python", "scripts/p4_entrypoint.py",
            "python", "-m", "pytest",
            "tests/test_auth.py", "tests/test_shadow_evidence.py",
            "-q", "--tb=no", "--junitxml=/tmp/p5a-targeted-postgres.xml",
        )
        command("docker", "cp", f"{ROOT / 'backend' / 'tests'}/.", f"{container}:/app/tests")
        test_process = command("docker", "start", "-a", container, check=False)
        args.junit_output.parent.mkdir(parents=True, exist_ok=True)
        copied = command(
            "docker", "cp", f"{container}:/tmp/p5a-targeted-postgres.xml",
            str(args.junit_output), check=False,
        )
        junit_copied = copied.returncode == 0
    finally:
        if database_created:
            manage("drop", args.database)
            database_removed = True

    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if junit_copied:
        root = ElementTree.parse(args.junit_output).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        for suite in suites:
            for key in counts:
                counts[key] += int(suite.attrib.get(key, 0))
    exit_code = test_process.returncode if test_process is not None else -1
    passed = (
        exit_code == 0 and junit_copied and counts["tests"] > 0
        and counts["failures"] == counts["errors"] == counts["skipped"] == 0
        and database_removed
    )
    result = {
        "evidence_type": "p5a_targeted_postgresql_remediation_tests",
        "status": "PASS" if passed else "FAIL",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "database": args.database,
        "database_created": database_created,
        "database_removed": database_removed,
        "main_database_modified": False,
        "runtime_volume_read_only": True,
        "test_container": container,
        "test_container_removed": False,
        "test_exit_code": exit_code,
        "test_output_sha256": hashlib.sha256(
            test_process.stdout if test_process is not None else b""
        ).hexdigest(),
        "junit_copied": junit_copied,
        "junit_sha256": hashlib.sha256(args.junit_output.read_bytes()).hexdigest()
        if junit_copied else None,
        **counts,
        "traceback_disabled": True,
        "secret_values_printed": False,
        "production_release_authorized": False,
        "production_traffic_switched": False,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_bytes(rendered.encode("utf-8"))
    print(json.dumps({
        "status": result["status"], "tests": counts["tests"],
        "failures": counts["failures"], "errors": counts["errors"],
        "skipped": counts["skipped"], "database_removed": database_removed,
        "secret_values_printed": False,
    }, sort_keys=True))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({
            "status": "FAIL", "error_type": type(exc).__name__,
            "secret_values_printed": False,
        }, sort_keys=True))
        raise SystemExit(1) from None
