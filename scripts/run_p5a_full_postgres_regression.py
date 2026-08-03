"""Run the complete P5A backend suite in four isolated tmpfs PostgreSQL batches."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
API_IMAGE = "renewable-p5a-api:5.0.0-p5a"
POSTGRES_IMAGE = "renewable-p5a-postgres:16.14"
NETWORK = "renewable-p5a-remediation-network"
RUNTIME_VOLUME = "renewable-p5a-remediation_p4_runtime"

BATCHES = (
    (
        "test_sqlbot_adapter.py", "test_semantic_registry.py", "test_procedure_skill_registry.py",
        "test_p3_credentials_retention.py", "test_p4_datasource_alerts.py", "test_p3_audit_release.py",
        "test_p5_production_gate_registry.py", "test_response_composer.py", "test_scenario_packages.py",
        "test_runtime_closeout.py", "test_query_security.py", "test_private_deployment_contract.py",
        "test_chatbi.py",
    ),
    (
        "test_platform_connectors.py", "test_dataset_release.py", "test_official_model_provider_validation.py",
        "test_p4_oidc_vault.py", "test_engine_router.py", "test_skill_evaluation_expansion.py",
        "test_sales_ops.py", "test_active_platform_query.py", "test_p5_enterprise_idp_acceptance.py",
        "test_platform_canary.py", "test_auth.py", "test_dual_engine_golden.py", "test_metrics_and_data.py",
    ),
    (
        "test_rag_golden_60.py", "test_memory_working_semantic_episodic.py", "test_mysql_connector.py",
        "test_knowledge_api_and_composite.py", "test_p3_identity_authorization.py",
        "test_platform_foundation_api.py", "test_memory_skill_orchestration_api.py",
        "test_sqlbot_quality_patch.py", "test_sqlbot_source_binding.py", "test_memory_scope_authorization.py",
        "test_metric_catalog.py", "test_observability.py", "test_readonly_boundary.py",
        "test_memory_evaluation_report.py",
    ),
    (
        "test_data_integration.py", "test_memory_governance_lifecycle.py", "test_initial_operational_skills.py",
        "test_knowledge_lifecycle.py", "test_shadow_evidence.py", "test_multi_scenario_chat.py",
        "test_live_model_provider_validation.py", "test_model_gateway.py", "test_memory_evaluation_expansion.py",
        "test_memory.py", "test_dashboard.py", "test_diagnostics.py", "test_revenue.py", "test_reports.py",
    ),
)
LABEL = re.compile(r"^p5a-postgres-[a-z0-9-]{4,48}$")


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.run(list(args), cwd=ROOT, capture_output=True)
    if check and process.returncode:
        raise RuntimeError(f"isolated regression command failed safely: {args[:3]}")
    return process


def junit_counts(path: Path) -> dict[str, int]:
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    for suite in suites:
        for key in counts:
            counts[key] += int(suite.attrib.get(key, 0))
    return counts


def wait_postgres(container: str, database: str, timeout: float = 180) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        probe = command(
            "docker", "exec", container,
            "pg_isready", "-h", "127.0.0.1", "-U", "alpha", "-d", database,
            check=False,
        )
        if probe.returncode == 0:
            return round(time.monotonic() - started, 3)
        time.sleep(1)
    raise RuntimeError(f"isolated PostgreSQL did not become ready: batch container {container}")


def run_batch(
    index: int, files: tuple[str, ...], output_dir: Path, stamp: str, label: str,
) -> dict:
    db_container = f"renewable-p5a-final-db-{index}-{stamp.lower()}"
    test_container = f"renewable-p5a-final-tests-{index}-{stamp.lower()}"
    database = f"p5a_final_batch_{index}"
    junit = output_dir / f"{label}-batch-{index}.xml"
    started_at = datetime.now(UTC)
    postgres_ready_seconds = None
    test_process: subprocess.CompletedProcess[bytes] | None = None
    junit_copied = False
    try:
        command(
            "docker", "create", "--name", db_container,
            "--network", NETWORK,
            "-v", f"{RUNTIME_VOLUME}:/run/p4-runtime:ro",
            "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=2147483648",
            "-e", f"POSTGRES_DB={database}",
            "-e", "POSTGRES_USER=alpha",
            "-e", "POSTGRES_PASSWORD_FILE=/run/p4-runtime/postgres_password",
            POSTGRES_IMAGE,
        )
        command("docker", "start", db_container)
        postgres_ready_seconds = wait_postgres(db_container, database)
        targets = [f"backend/tests/{name}" for name in files]
        command(
            "docker", "create", "--name", test_container,
            "--network", NETWORK,
            "-v", f"{RUNTIME_VOLUME}:/run/p4-runtime:ro",
            "-e", "APP_ENV=test",
            "-e", "AUTO_BOOTSTRAP_DEMO_USERS=true",
            "-e", f"ACCEPTANCE_POSTGRES_HOST={db_container}",
            "-e", f"ACCEPTANCE_POSTGRES_DB={database}",
            "-e", "ACCEPTANCE_TEST_DATABASE_URL_FROM_RUNTIME=true",
            "-w", "/app",
            API_IMAGE,
            "python", "scripts/p4_entrypoint.py", "python", "-m", "pytest",
            *targets,
            "-q", "--tb=no", f"--junitxml=/tmp/{junit.name}",
        )
        command("docker", "cp", str(ROOT / "backend"), f"{test_container}:/app/backend")
        command("docker", "cp", str(ROOT / "deploy"), f"{test_container}:/app/deploy")
        command("docker", "cp", f"{ROOT / 'docs'}/.", f"{test_container}:/app/docs")
        command("docker", "cp", str(ROOT / "samples"), f"{test_container}:/app/samples")
        test_process = command("docker", "start", "-a", test_container, check=False)
        copied = command(
            "docker", "cp", f"{test_container}:/tmp/{junit.name}", str(junit), check=False,
        )
        junit_copied = copied.returncode == 0
    finally:
        test_removed = command("docker", "rm", "-f", test_container, check=False).returncode == 0
        db_removed = command("docker", "rm", "-f", db_container, check=False).returncode == 0
    counts = junit_counts(junit) if junit_copied else {
        "tests": 0, "failures": 0, "errors": 0, "skipped": 0,
    }
    exit_code = test_process.returncode if test_process is not None else -1
    return {
        "batch": index,
        "status": "PASS" if (
            exit_code == 0 and junit_copied and counts["tests"] > 0
            and counts["failures"] == counts["errors"] == counts["skipped"] == 0
            and test_removed and db_removed
        ) else "FAIL",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "postgres_ready_seconds": postgres_ready_seconds,
        "database": database,
        "tmpfs_postgresql": True,
        "persistent_volume_attached": False,
        "test_files": list(files),
        "test_exit_code": exit_code,
        "test_output_sha256": hashlib.sha256(
            test_process.stdout if test_process is not None else b""
        ).hexdigest(),
        "junit": junit.name,
        "junit_sha256": hashlib.sha256(junit.read_bytes()).hexdigest() if junit_copied else None,
        "test_container_removed": test_removed,
        "database_container_removed": db_removed,
        **counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--knowledge-rerun", action="store_true",
        help="Rerun the one knowledge lifecycle file after correcting test asset layout.",
    )
    parser.add_argument(
        "--gate-rerun", action="store_true",
        help="Rerun the production gate registry file after tightening the 28-gate contract.",
    )
    args = parser.parse_args()
    if args.knowledge_rerun and args.gate_rerun:
        parser.error("choose only one focused rerun")
    if not LABEL.fullmatch(args.label):
        parser.error("label must use the p5a-postgres- prefix")
    paths = [args.output_dir / f"{args.label}-batch-{index}.xml" for index in range(1, 5)]
    if args.summary_output.exists() or any(path.exists() for path in paths):
        raise RuntimeError("refusing to overwrite final PostgreSQL regression evidence")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC)
    stamp = started_at.strftime("%Y%m%d%H%M%S")
    if args.knowledge_rerun:
        jobs = [(1, ("test_knowledge_lifecycle.py",))]
    elif args.gate_rerun:
        jobs = [(1, ("test_p5_production_gate_registry.py",))]
    else:
        jobs = list(enumerate(BATCHES, start=1))
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [
            pool.submit(run_batch, index, files, args.output_dir, stamp, args.label)
            for index, files in jobs
        ]
        batches = [future.result() for future in futures]
    totals = {
        key: sum(batch[key] for batch in batches)
        for key in ("tests", "failures", "errors", "skipped")
    }
    if args.knowledge_rerun:
        expected_totals = {"tests": 4, "failures": 0, "errors": 0, "skipped": 0}
    elif args.gate_rerun:
        expected_totals = {"tests": 5, "failures": 0, "errors": 0, "skipped": 0}
    else:
        expected_totals = {"tests": 359, "failures": 0, "errors": 0, "skipped": 0}
    passed = (
        all(batch["status"] == "PASS" for batch in batches)
        and totals == expected_totals
    )
    result = {
        "evidence_type": (
            "p5a_postgresql_knowledge_asset_corrective_rerun"
            if args.knowledge_rerun else (
                "p5a_postgresql_gate_contract_corrective_rerun"
                if args.gate_rerun else "p5a_postgresql_final_full_regression"
            )
        ),
        "status": "PASS" if passed else "FAIL",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "environment": "four isolated tmpfs PostgreSQL 16.14 databases",
        "data_classification": "simulated",
        "application_image": API_IMAGE,
        "postgres_image": POSTGRES_IMAGE,
        "batches": batches,
        "totals": totals,
        "main_database_modified": False,
        "persistent_test_volume_created": False,
        "temporary_containers_removed": all(
            batch["test_container_removed"] and batch["database_container_removed"]
            for batch in batches
        ),
        "secret_values_printed": False,
        "production_release_authorized": False,
        "production_traffic_switched": False,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_bytes(rendered.encode("utf-8"))
    print(json.dumps({
        "status": result["status"], **totals,
        "temporary_containers_removed": result["temporary_containers_removed"],
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
