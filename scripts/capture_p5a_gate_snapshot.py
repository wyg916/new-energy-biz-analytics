"""Capture a governed P5A gate snapshot and immutable local histories without tokens."""

from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_CONTAINER = "renewable-p5a-remediation-api-1"
BASE_URL = "https://127.0.0.1:8445/api/v1"
HOST = "p5a.localhost"
LOCAL_CODES = (
    "REMOTE_PUSH", "DOCKER_RUNTIME", "POSTGRES_CANONICAL_REGRESSION", "FRONTEND_E2E",
    "IMAGE_SECURITY", "KEYCLOAK_SECURITY", "VAULT_SECURITY", "SQLBOT_IMAGE_SECURITY",
    "CAPACITY_SOAK", "BACKUP_RECOVERY", "RAG_MODE", "BACKUP_RESTORE", "ROLLBACK_DRILL",
)


def command(*args: str) -> str:
    process = subprocess.run(
        list(args), cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
    )
    if process.returncode:
        raise RuntimeError(f"gate snapshot command failed safely: {args[:3]}")
    return process.stdout.strip()


def identity() -> tuple[str, str]:
    code = (
        "import sys; sys.path.insert(0, '/app/scripts'); import json; "
        "from run_p4_capacity_soak import token_for; token, sid = token_for('analyst'); "
        "print(json.dumps({'token': token, 'session_id': sid}))"
    )
    output = command(
        "docker", "exec", API_CONTAINER,
        "python", "scripts/p4_entrypoint.py", "python", "-c", code,
    )
    payload = json.loads(output.splitlines()[-1])
    return str(payload["token"]), str(payload["session_id"])


def revoke(session_id: str) -> None:
    code = (
        "from app.preproduction.oidc import OIDCSessionStore; "
        f"OIDCSessionStore().revoke_session({session_id!r}); print('revoked')"
    )
    command(
        "docker", "exec", API_CONTAINER,
        "python", "scripts/p4_entrypoint.py", "python", "-c", code,
    )


def get(path: str, token: str) -> dict:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}", "Host": HOST},
    )
    with urllib.request.urlopen(
        request, timeout=30, context=ssl._create_unverified_context(),
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("refusing to overwrite gate snapshot evidence")
    token, session_id = identity()
    try:
        snapshot = get("/production-acceptance/snapshot", token)
        histories = {
            code: get(f"/production-acceptance/gates/{code}/history", token)["history"]
            for code in LOCAL_CODES
        }
    finally:
        revoke(session_id)
    gates = snapshot["gates"]
    local = [gate for gate in gates if not gate["external_condition"]]
    external = [gate for gate in gates if gate["external_condition"]]
    waivers = [gate["gate_code"] for gate in gates if gate["recorded_status"] == "WAIVED"]
    passed_without_evidence = [
        gate["gate_code"] for gate in gates
        if gate["status"] == "PASSED" and (not gate["evidence"] or not gate["evidence_hash"])
    ]
    checks = {
        "gate_count_28": len(gates) == 28,
        "local_gate_count_13": len(local) == 13,
        "external_gate_count_15": len(external) == 15,
        "external_gates_remain_open_conditional": all(
            gate["recorded_status"] == "OPEN" and gate["display_status"] == "CONDITIONAL"
            for gate in external
        ),
        "waivers_zero": not waivers,
        "passed_gates_have_evidence": not passed_without_evidence,
        "no_go": snapshot["summary"]["go_no_go_recommendation"] == "NO_GO",
        "acceptance_not_ready": snapshot["summary"]["production_acceptance_ready"] is False,
        "release_not_authorized": snapshot["runtime_contract"]["production_release_authorized"] is False,
        "traffic_not_switched": snapshot["runtime_contract"]["production_traffic_switched"] is False,
        "sqlbot_canary_false": snapshot["runtime_contract"]["sqlbot_canary_eligible"] is False,
    }
    payload = {
        "evidence_type": "p5a_production_gate_pre_push_snapshot",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "captured_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "counts": snapshot["summary"]["counts"],
        "unresolved_blockers": snapshot["summary"]["unresolved_blockers"],
        "local_gate_codes": sorted(gate["gate_code"] for gate in local),
        "external_gate_codes": sorted(gate["gate_code"] for gate in external),
        "waived_gate_codes": waivers,
        "passed_without_evidence": passed_without_evidence,
        "snapshot": snapshot,
        "local_histories": histories,
        "token_printed": False,
        "external_gates_modified": False,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rendered.encode("utf-8"))
    print(json.dumps({
        "status": payload["status"], "counts": payload["counts"],
        "waivers": len(waivers),
        "evidence_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "token_printed": False,
    }, sort_keys=True))
    raise SystemExit(0 if payload["status"] == "PASS" else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({
            "status": "FAIL", "error_type": type(exc).__name__, "token_printed": False,
        }, sort_keys=True))
        raise SystemExit(1) from None
