"""Execute the non-destructive P5B image/config and isolated migration rollback drill."""

from __future__ import annotations

import hashlib
import json
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "deploy" / "preproduction" / "compose.yaml"
CURRENT = ROOT / "deploy" / "production-acceptance" / "p5b.override.yaml"
ROLLBACK = ROOT / "deploy" / "production-acceptance" / "p5b.rollback.override.yaml"
PROJECT = "renewable-p5b-gate-closure"
BASE_URL = "https://127.0.0.1:8446/api/v1"
HOST = "p5b.localhost"
SERVICES = ("api", "web", "db", "oidc", "vault")
CORE_TABLES = ("fact_charging_session", "sales_order", "sales_order_item")
METADATA_TABLES = (
    "release_record", "platform_release", "governance_policy", "scenario_package_release",
    "semantic_model", "semantic_model_version", "knowledge_document",
    "knowledge_document_version", "credential_reference", "memory_record",
    "skill_definition", "production_gate_registry", "production_gate_history",
)


def run(*args: str, check: bool = True, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.run(list(args), cwd=ROOT, input=input_bytes, capture_output=True)
    if check and process.returncode:
        raise RuntimeError(f"rollback command failed safely: {args[:4]}")
    return process


def compose(*args: str, rollback: bool = False, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    files = ["-f", str(BASE), "-f", str(CURRENT)]
    if rollback:
        files += ["-f", str(ROLLBACK)]
    return run("docker", "compose", "-p", PROJECT, *files, *args, check=check)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request(path: str, token: str | None = None, payload: dict | None = None) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Host": HOST}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers),
            context=ssl._create_unverified_context(), timeout=30,
        ) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except (OSError, TimeoutError):
        return 0, {}


def wait_ready(timeout: float = 240) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if request("/health/ready")[0] == 200:
            return round(time.monotonic() - started, 3)
        time.sleep(1)
    raise RuntimeError("P5B readiness did not recover")


def psql(database: str, sql: str) -> str:
    process = run(
        "docker", "exec", f"{PROJECT}-backup-1", "sh", "-ec",
        'export PGPASSWORD="$(sed -n \'1p\' /run/p4-runtime/postgres_password)"; '
        'exec psql -h db -U alpha -d "$1" -At -v ON_ERROR_STOP=1 -c "$2"',
        "--", database, sql,
    )
    return process.stdout.decode("utf-8").strip()


def db_snapshot(database: str, *, include_p5: bool = True) -> dict:
    tables = list(CORE_TABLES) + list(METADATA_TABLES)
    if not include_p5:
        tables = [name for name in tables if not name.startswith("production_gate")]
    result = {}
    for table in tables:
        row_json = (
            "to_jsonb(t) - 'published_at' - 'activated_at' - 'validated_at'"
            if table == "scenario_package_release" else "row_to_json(t)"
        )
        value = psql(database, (
            "SELECT json_build_object('count',count(*),'hash',"
            f"md5(coalesce(sum(hashtextextended(({row_json})::text,0)::numeric),0)::text))::text "
            f"FROM {table} t"
        ))
        result[table] = json.loads(value)
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
    core = {name: result[name] for name in CORE_TABLES}
    protected = {
        name: value for name, value in result.items()
        if name not in {*CORE_TABLES, "memory_record", "production_gate_history"}
    }
    return {
        "tables": result,
        "sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "core_business_sha256": hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest(),
        "protected_metadata_sha256": hashlib.sha256(json.dumps(protected, sort_keys=True).encode()).hexdigest(),
    }


def migration(database: str, *command: str) -> str:
    process = compose(
        "run", "--rm", "-e", f"ACCEPTANCE_POSTGRES_DB={database}", "migrate",
        "python", "scripts/p4_entrypoint.py", "alembic", *command,
    )
    return process.stdout.decode("utf-8", errors="replace").strip()


def revision(database: str) -> str:
    return psql(database, "SELECT version_num FROM alembic_version")


def images() -> dict:
    values = {}
    for service in SERVICES:
        container = f"{PROJECT}-{service}-1"
        raw = run("docker", "inspect", container, "--format", "{{json .}}").stdout
        item = json.loads(raw.decode("utf-8"))
        values[service] = {"image_id": item["Image"], "configured_image": item["Config"]["Image"]}
    return values


def token() -> tuple[str, str]:
    code = (
        "import sys; sys.path.insert(0, '/app/scripts'); import json; "
        "from run_p4_capacity_soak import token_for; "
        "value, session = token_for('analyst'); "
        "print(json.dumps({'token': value, 'session_id': session}))"
    )
    output = run(
        "docker", "exec", f"{PROJECT}-api-1", "python", "scripts/p4_entrypoint.py",
        "python", "-c", code,
    ).stdout.decode("utf-8")
    payload = json.loads(output.splitlines()[-1])
    return payload["token"], payload["session_id"]


def revoke(session_id: str) -> None:
    code = (
        "from app.preproduction.oidc import OIDCSessionStore; "
        f"OIDCSessionStore().revoke_session({session_id!r})"
    )
    run(
        "docker", "exec", f"{PROJECT}-api-1", "python", "scripts/p4_entrypoint.py",
        "python", "-c", code, check=False,
    )


def runtime_contract() -> dict:
    access_token, session_id = token()
    try:
        probes = {
            "knowledge": request("/knowledge/runtime", access_token),
            "memory": request("/memory/records?scenario_id=charging_ops", access_token),
            "skills": request("/skills", access_token),
            "gates": request("/production-acceptance/snapshot", access_token),
            "deterministic_query": request("/assistant/query", access_token, {
                "question": "2026年6月充电收入是多少？",
                "scenario_id": "charging_ops",
                "profile": "executive_brief",
                "conversation_id": "p5b-rollback-drill",
            }),
        }
    finally:
        revoke(session_id)
    query = probes["deterministic_query"][1]
    return {
        "http_statuses": {name: value[0] for name, value in probes.items()},
        "deterministic_engine": query.get("engine") or (query.get("data_query_evidence") or {}).get("engine"),
        "query_completed": (query.get("data_query_evidence") or {}).get("status") == "completed",
        "sqlbot_runtime": probes["knowledge"][1].get("sqlbot_runtime"),
        "all_http_200": all(value[0] == 200 for value in probes.values()),
    }


def create_backup_and_clone(temp_database: str, stamp: str) -> dict:
    script = r'''
set -eu
target="/backups/p5b-rollback-$2.dump"
export PGPASSWORD="$(sed -n '1p' /run/p4-runtime/postgres_password)"
test "$(psql -h db -U alpha -d postgres -At -c "SELECT count(*) FROM pg_database WHERE datname='$1'")" = 0
pg_dump -h db -U alpha -d renewable_p5b --format=custom --no-owner --file="$target"
createdb -h db -U alpha "$1"
pg_restore -h db -U alpha -d "$1" --no-owner --exit-on-error "$target"
printf '{"path":"%s","sha256":"%s","size_bytes":%s}' "$target" "$(sha256sum "$target" | sed 's/ .*//')" "$(wc -c < "$target" | tr -d ' ')"
'''
    output = run(
        "docker", "exec", "-i", f"{PROJECT}-backup-1", "sh", "-s", "--",
        temp_database, stamp, input_bytes=script.encode("utf-8"),
    ).stdout.decode("utf-8")
    return json.loads(output)


def restore_gate_audit(database: str, backup_path: str) -> None:
    script = r'''
set -eu
export PGPASSWORD="$(sed -n '1p' /run/p4-runtime/postgres_password)"
pg_restore -h db -U alpha -d "$1" --data-only --no-owner --exit-on-error --table=production_gate_registry "$2"
pg_restore -h db -U alpha -d "$1" --data-only --no-owner --exit-on-error --table=production_gate_history "$2"
'''
    run(
        "docker", "exec", "-i", f"{PROJECT}-backup-1", "sh", "-s", "--",
        database, backup_path, input_bytes=script.encode("utf-8"),
    )


def drop_temp_database(database: str) -> bool:
    process = run(
        "docker", "exec", f"{PROJECT}-backup-1", "sh", "-ec",
        'export PGPASSWORD="$(sed -n \'1p\' /run/p4-runtime/postgres_password)"; '
        'dropdb -h db -U alpha --if-exists "$1"', "--", database, check=False,
    )
    return process.returncode == 0


def main() -> None:
    output = ROOT / "docs" / "platformization" / "p5b" / "evidence" / "p5b-rollback-drill.json"
    if output.exists():
        raise RuntimeError("refusing to overwrite rollback evidence")
    started_at = datetime.now(UTC)
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    temp_database = f"p5b_rollback_verify_{started_at.strftime('%Y%m%d%H%M%S')}"
    recovery_started = None
    temp_removed = False
    result: dict = {}
    try:
        compose("up", "-d", "--no-build")
        current_ready = wait_ready()
        before_images = images()
        before_db = db_snapshot("renewable_p5b")
        backup = create_backup_and_clone(temp_database, stamp)
        clone_before = db_snapshot(temp_database)
        before_revision = revision(temp_database)

        rollback_started = time.monotonic()
        compose("up", "-d", "--no-build", rollback=True)
        previous_ready = wait_ready()
        previous_images = images()
        previous_contract = runtime_contract()
        rollback_seconds = round(time.monotonic() - rollback_started, 3)

        migration(temp_database, "downgrade", "p4_0001")
        downgraded_revision = revision(temp_database)
        clone_downgraded = db_snapshot(temp_database, include_p5=False)
        migration(temp_database, "upgrade", "p5_0001")
        upgraded_revision = revision(temp_database)
        restore_gate_audit(temp_database, backup["path"])
        clone_after = db_snapshot(temp_database)

        recovery_started = time.monotonic()
        compose("up", "-d", "--no-build")
        recovered_ready = wait_ready()
        recovered_images = images()
        recovered_contract = runtime_contract()
        recovery_seconds = round(time.monotonic() - recovery_started, 3)
        after_db = db_snapshot("renewable_p5b")
        temp_removed = drop_temp_database(temp_database)

        result = {
            "schema_version": "1.0", "evidence_type": "p5b_actual_rollback_drill",
            "status": "PASS", "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "environment": "P5B local preproduction, not production",
            "source_git_sha": run("git", "rev-parse", "HEAD").stdout.decode().strip(),
            "working_tree_diff_sha256": hashlib.sha256(run("git", "diff", "--binary").stdout).hexdigest(),
            "configuration_sha256": {"current": sha(CURRENT), "previous": sha(ROLLBACK)},
            "artifacts_sha256": {
                "policy_bundle": sha(ROOT / "backend" / "app" / "governance" / "authorization.py"),
                "scenario_contract": sha(ROOT / "scenarios" / "charging_ops" / "manifest.yaml"),
                "semantic_model": sha(ROOT / "scenarios" / "charging_ops" / "metrics.yaml"),
                "rag_release": sha(ROOT / "docs" / "platformization" / "p5" / "evidence" / "rag-keyword-release.json"),
            },
            "backup": backup, "current_ready_seconds": current_ready,
            "rollback_seconds": rollback_seconds, "previous_ready_seconds": previous_ready,
            "recovery_seconds": recovery_seconds, "recovered_ready_seconds": recovered_ready,
            "images": {"before": before_images, "previous": previous_images, "recovered": recovered_images},
            "database": {
                "source_before": before_db, "source_after": after_db,
                "source_core_hash_preserved": before_db["core_business_sha256"] == after_db["core_business_sha256"],
                "source_protected_metadata_hash_preserved": before_db["protected_metadata_sha256"] == after_db["protected_metadata_sha256"],
                "isolated_clone_before": clone_before, "isolated_clone_downgraded": clone_downgraded,
                "isolated_clone_after": clone_after,
                "isolated_cycle_hash_preserved": clone_before["sha256"] == clone_after["sha256"],
                "revision_before": before_revision, "revision_downgraded": downgraded_revision,
                "revision_upgraded": upgraded_revision, "temporary_database_removed": temp_removed,
                "source_database_modified_by_migration_cycle": False,
            },
            "runtime_contract": {"previous": previous_contract, "recovered": recovered_contract},
            "volumes_deleted": False, "audit_history_deleted_from_source": False,
            "secret_values_printed": False, "production_release_authorized": False,
            "production_traffic_switched": False,
        }
        passed = (
            before_images == recovered_images and previous_images != before_images
            and previous_contract["all_http_200"] and recovered_contract["all_http_200"]
            and before_revision == upgraded_revision == "p5_0001"
            and downgraded_revision == "p4_0001"
            and result["database"]["source_core_hash_preserved"]
            and result["database"]["source_protected_metadata_hash_preserved"]
            and result["database"]["isolated_cycle_hash_preserved"] and temp_removed
            and previous_contract["query_completed"] and recovered_contract["query_completed"]
        )
        result["status"] = "PASS" if passed else "FAIL"
    finally:
        compose("up", "-d", "--no-build", check=False)
        if not temp_removed:
            temp_removed = drop_temp_database(temp_database)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(json.dumps({
        "status": result.get("status", "FAIL"), "rollback_seconds": result.get("rollback_seconds"),
        "recovery_seconds": result.get("recovery_seconds"), "evidence_sha256": sha(output),
        "secret_values_printed": False,
    }, sort_keys=True))
    raise SystemExit(0 if result.get("status") == "PASS" else 1)


if __name__ == "__main__":
    main()
