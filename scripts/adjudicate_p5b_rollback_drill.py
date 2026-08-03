"""Adjudicate the completed P5B rollback drill after correcting two probes.

The original evidence is preserved. This script re-probes both API images with
the required Memory query parameter and compares stable scenario-package fields
against the original backup without repeating the expensive data restore.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from run_p5b_rollback_drill import (
    CURRENT,
    PROJECT,
    ROOT,
    compose,
    drop_temp_database,
    images,
    psql,
    run,
    runtime_contract,
    wait_ready,
)


EVIDENCE = ROOT / "docs" / "platformization" / "p5b" / "evidence"
ATTEMPT = EVIDENCE / "p5b-rollback-drill-attempt-1.json"
CORRECTED_ATTEMPT = EVIDENCE / "p5b-rollback-drill-attempt-2.json"
OUTPUT = EVIDENCE / "p5b-rollback-drill.json"


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_scenario_snapshot(database: str) -> dict:
    raw = psql(database, (
        "SELECT json_build_object('count',count(*),'hash',"
        "md5(coalesce(sum(hashtextextended((to_jsonb(t)-'published_at'-'activated_at'-'validated_at')::text,0)::numeric),0)::text))::text "
        "FROM scenario_package_release t"
    ))
    return json.loads(raw)


def restore_schema_and_scenario(database: str, backup_path: str) -> None:
    script = r'''
set -eu
export PGPASSWORD="$(sed -n '1p' /run/p4-runtime/postgres_password)"
test "$(psql -h db -U alpha -d postgres -At -c "SELECT count(*) FROM pg_database WHERE datname='$1'")" = 0
createdb -h db -U alpha "$1"
pg_restore -h db -U alpha -d "$1" --no-owner --exit-on-error --section=pre-data "$2"
pg_restore -h db -U alpha -d "$1" --no-owner --exit-on-error --data-only --table=scenario_package_release "$2"
'''
    run(
        "docker", "exec", "-i", f"{PROJECT}-backup-1", "sh", "-s", "--",
        database, backup_path, input_bytes=script.encode("utf-8"),
    )


def api_image() -> dict:
    return images()["api"]


def main() -> None:
    if not ATTEMPT.exists():
        raise RuntimeError("preserved rollback attempt evidence is missing")
    if OUTPUT.exists():
        raise RuntimeError("refusing to overwrite final rollback evidence")
    attempt = json.loads(ATTEMPT.read_text(encoding="utf-8"))
    corrected_attempt = (
        json.loads(CORRECTED_ATTEMPT.read_text(encoding="utf-8"))
        if CORRECTED_ATTEMPT.exists() else None
    )
    if attempt.get("status") != "FAIL":
        raise RuntimeError("attempt must retain its original FAIL status")

    changed_protected = sorted(
        name for name, before in attempt["database"]["source_before"]["tables"].items()
        if name not in {"memory_record", "production_gate_history"}
        and before != attempt["database"]["source_after"]["tables"].get(name)
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    temp_database = f"p5b_rollback_adjudicate_{stamp}"
    temp_removed = False
    current_before = api_image()
    try:
        restore_schema_and_scenario(temp_database, attempt["backup"]["path"])
        scenario_before = stable_scenario_snapshot(temp_database)
        scenario_after = stable_scenario_snapshot("renewable_p5b")

        if corrected_attempt:
            probes = corrected_attempt["corrected_probes"]
            previous_ready_seconds = probes["previous_ready_seconds"]
            recovered_ready_seconds = probes["recovered_ready_seconds"]
            previous_image = probes["previous_api_image"]
            recovered_image = probes["recovered_api_image"]
            previous_contract = probes["previous_contract"]
            recovered_contract = probes["recovered_contract"]
        else:
            compose("up", "-d", "--no-deps", "--force-recreate", "api", rollback=True)
            previous_ready_seconds = wait_ready()
            previous_image = api_image()
            previous_contract = runtime_contract()

            compose("up", "-d", "--no-deps", "--force-recreate", "api")
            recovered_ready_seconds = wait_ready()
            recovered_image = api_image()
            recovered_contract = runtime_contract()
        temp_removed = drop_temp_database(temp_database)
    finally:
        compose("up", "-d", "--no-deps", "--force-recreate", "api", check=False)
        if not temp_removed:
            temp_removed = drop_temp_database(temp_database)

    db = attempt["database"]
    original_failure_is_probe_only = (
        attempt["runtime_contract"]["previous"]["http_statuses"].get("memory") == 422
        and attempt["runtime_contract"]["recovered"]["http_statuses"].get("memory") == 422
        and changed_protected == ["scenario_package_release"]
    )
    actual_rollback_invariants = (
        db["source_core_hash_preserved"]
        and db["isolated_cycle_hash_preserved"]
        and db["revision_before"] == db["revision_upgraded"] == "p5_0001"
        and db["revision_downgraded"] == "p4_0001"
        and db["temporary_database_removed"]
        and attempt["images"]["before"] == attempt["images"]["recovered"]
        and attempt["images"]["previous"] != attempt["images"]["before"]
        and attempt["runtime_contract"]["previous"]["query_completed"]
        and attempt["runtime_contract"]["recovered"]["query_completed"]
    )
    passed = (
        original_failure_is_probe_only
        and actual_rollback_invariants
        and scenario_before == scenario_after
        and previous_contract["all_http_200"]
        and recovered_contract["all_http_200"]
        and previous_image != current_before
        and recovered_image == current_before
        and temp_removed
    )
    payload = {
        "schema_version": "1.0",
        "evidence_type": "p5b_actual_rollback_drill_adjudication",
        "status": "PASS" if passed else "FAIL",
        "finished_at": datetime.now(UTC).isoformat(),
        "environment": "P5B local preproduction, not production",
        "source_git_sha": run("git", "rev-parse", "HEAD").stdout.decode().strip(),
        "actual_attempt": {
            "path": str(ATTEMPT.relative_to(ROOT)).replace("\\", "/"),
            "sha256": file_sha(ATTEMPT),
            "original_status": attempt["status"],
            "rollback_seconds": attempt["rollback_seconds"],
            "recovery_seconds": attempt["recovery_seconds"],
            "failure_classification": "MEASUREMENT_DEFECT_NOT_ROLLBACK_DEFECT",
        },
        "corrected_probe_attempt": ({
            "path": str(CORRECTED_ATTEMPT.relative_to(ROOT)).replace("\\", "/"),
            "sha256": file_sha(CORRECTED_ATTEMPT),
            "status": corrected_attempt["status"],
            "purpose": "corrected API contract probe evidence",
        } if corrected_attempt else None),
        "actual_rollback_invariants_passed": actual_rollback_invariants,
        "corrected_probes": {
            "previous_ready_seconds": previous_ready_seconds,
            "recovered_ready_seconds": recovered_ready_seconds,
            "previous_contract": previous_contract,
            "recovered_contract": recovered_contract,
            "previous_api_image": previous_image,
            "recovered_api_image": recovered_image,
        },
        "database": {
            "core_business_hash_preserved": db["source_core_hash_preserved"],
            "isolated_migration_cycle_hash_preserved": db["isolated_cycle_hash_preserved"],
            "revisions": [db["revision_before"], db["revision_downgraded"], db["revision_upgraded"]],
            "changed_protected_tables_under_raw_hash": changed_protected,
            "scenario_package_stable_fields_before": scenario_before,
            "scenario_package_stable_fields_after": scenario_after,
            "scenario_package_stable_fields_preserved": scenario_before == scenario_after,
            "temporary_databases_removed": db["temporary_database_removed"] and temp_removed,
        },
        "probe_corrections": {
            "memory_query_parameter_added": "scenario_id=charging_ops",
            "scenario_package_volatile_fields_excluded": ["published_at", "activated_at", "validated_at"],
            "original_failure_is_probe_only": original_failure_is_probe_only,
        },
        "volumes_deleted": False,
        "production_release_authorized": False,
        "production_traffic_switched": False,
        "secret_values_printed": False,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "evidence_sha256": file_sha(OUTPUT)}, sort_keys=True))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
