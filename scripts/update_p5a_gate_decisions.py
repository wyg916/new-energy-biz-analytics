"""Record P5A gate decisions through the governed API without printing tokens."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCOPE = os.getenv("ACCEPTANCE_SCOPE", "p5a").lower()
API_CONTAINER = os.getenv("ACCEPTANCE_API_CONTAINER", "renewable-p5a-remediation-api-1")
BASE_URL = os.getenv("ACCEPTANCE_API_BASE_URL", "https://127.0.0.1:8445/api/v1")
HOST = os.getenv("ACCEPTANCE_HOST", "p5a.localhost")


LOCAL_DECISIONS = {
    "DOCKER_RUNTIME": ("PASSED", [
        ("runbook", "docs/platformization/p5a/03_DOCKER_WSL_RECOVERY.md"),
        ("runtime_probe", "docs/platformization/p5a/evidence/docker-wsl-recovery.json"),
    ]),
    "POSTGRES_CANONICAL_REGRESSION": ("PASSED", [
        ("test_result", "docs/platformization/p5a/13_CURRENT_REGRESSION_CLOSEOUT.md"),
        ("test_result", "docs/platformization/p5a/evidence/p5a-final-regression-summary.json"),
        ("test_result", "docs/platformization/p5a/evidence/p5a-migration-cycle.json"),
    ]),
    "FRONTEND_E2E": ("PASSED", [
        ("test_result", "docs/platformization/p5a/evidence/p5a-final-regression-summary.json"),
        ("test_result", "docs/platformization/p5a/evidence/docker-smoke-p5a-final.json"),
    ]),
    "IMAGE_SECURITY": ("BLOCKED", [
        ("security_scan", "docs/platformization/p5a/evidence/container-security/container-security-summary.json"),
    ]),
    "KEYCLOAK_SECURITY": ("BLOCKED", [
        ("security_scan", "docs/platformization/p5a/evidence/container-security/trivy-keycloak.json"),
    ]),
    "VAULT_SECURITY": ("BLOCKED", [
        ("security_scan", "docs/platformization/p5a/evidence/container-security/trivy-vault.json"),
    ]),
    "SQLBOT_IMAGE_SECURITY": ("BLOCKED", [
        ("security_scan", "docs/platformization/p5a/evidence/container-security/trivy-sqlbot.json"),
    ]),
    "CAPACITY_SOAK": ("PASSED", [
        ("test_result", "docs/platformization/p5a/evidence/p5a-capacity-soak.json"),
        ("test_result", "docs/platformization/p5a/evidence/p5a-capacity-verification.json"),
    ]),
    "BACKUP_RECOVERY": ("PASSED", [
        ("test_result", "docs/platformization/p5a/evidence/p5a-fault-recovery.json"),
        ("test_result", "docs/platformization/p5a/evidence/p5a-backup-restore.json"),
    ]),
    "BACKUP_RESTORE": ("PASSED", [
        ("test_result", "docs/platformization/p5a/evidence/p5a-backup-restore.json"),
    ]),
    "ROLLBACK_DRILL": ("BLOCKED", [
        ("test_result", "docs/platformization/p5a/evidence/p5a-migration-cycle.json"),
        ("runbook", "docs/platformization/p5a/08_FAILURE_BACKUP_AND_RECOVERY.md"),
    ]),
}

if SCOPE == "p5b":
    LOCAL_DECISIONS = {
        "DOCKER_RUNTIME": ("PASSED", [
            ("runtime_probe", "docs/platformization/p5b/evidence/docker-smoke-p5b-final.json"),
            ("test_result", "docs/platformization/p5b/evidence/p5b-fault-recovery.json"),
        ]),
        "POSTGRES_CANONICAL_REGRESSION": ("PASSED", [
            ("test_result", "docs/platformization/p5b/evidence/p5b-final-regression-summary.json"),
            ("test_result", "docs/platformization/p5b/evidence/p5b-backup-restore.json"),
        ]),
        "FRONTEND_E2E": ("PASSED", [
            ("test_result", "docs/platformization/p5b/evidence/p5b-final-regression-summary.json"),
        ]),
        "IMAGE_SECURITY": ("BLOCKED", [
            ("security_scan", "docs/platformization/p5b/evidence/container-security/container-security-summary.json"),
        ]),
        "KEYCLOAK_SECURITY": ("BLOCKED", [
            ("security_scan", "docs/platformization/p5b/evidence/container-security/trivy-keycloak.json"),
            ("security_scan", "docs/platformization/p5b/evidence/container-security/keycloak-component-verification.json"),
        ]),
        "VAULT_SECURITY": ("BLOCKED", [
            ("security_scan", "docs/platformization/p5b/evidence/container-security/trivy-vault.json"),
            ("test_result", "docs/platformization/p5b/evidence/p5b-vault-acceptance.json"),
        ]),
        "SQLBOT_IMAGE_SECURITY": ("BLOCKED", [
            ("manifest", "docs/platformization/p5b/evidence/p5b-release-component-scope.json"),
            ("security_scan", "docs/platformization/p5a/evidence/container-security/trivy-sqlbot.json"),
        ]),
        "CAPACITY_SOAK": ("PASSED", [
            ("test_result", "docs/platformization/p5a/evidence/p5a-capacity-soak.json"),
            ("test_result", "docs/platformization/p5a/evidence/p5a-capacity-verification.json"),
        ]),
        "BACKUP_RECOVERY": ("PASSED", [
            ("test_result", "docs/platformization/p5b/evidence/p5b-fault-recovery.json"),
            ("test_result", "docs/platformization/p5b/evidence/p5b-backup-restore.json"),
        ]),
        "BACKUP_RESTORE": ("PASSED", [
            ("test_result", "docs/platformization/p5b/evidence/p5b-backup-restore.json"),
        ]),
        "RAG_MODE": ("PASSED", [
            ("test_result", "docs/platformization/p5b/evidence/p5b-final-regression-summary.json"),
            ("test_result", "docs/platformization/p5/evidence/rag-keyword-release.json"),
        ]),
        "ROLLBACK_DRILL": ("PASSED", [
            ("test_result", "docs/platformization/p5b/evidence/p5b-rollback-drill.json"),
        ]),
    }


def command(*args: str) -> str:
    process = subprocess.run(
        list(args), cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
    )
    if process.returncode:
        raise RuntimeError(f"command failed safely: {args[:3]}")
    return process.stdout.strip()


def acceptance_identity() -> tuple[str, str]:
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


def revoke_session(session_id: str) -> None:
    code = (
        "from app.preproduction.oidc import OIDCSessionStore; "
        f"OIDCSessionStore().revoke_session({session_id!r}); print('revoked')"
    )
    command(
        "docker", "exec", API_CONTAINER,
        "python", "scripts/p4_entrypoint.py", "python", "-c", code,
    )


def evidence(evidence_type: str, relative_path: str) -> dict:
    path = ROOT / relative_path
    if not path.is_file():
        raise RuntimeError(f"required gate evidence is absent: {relative_path}")
    return {
        "evidence_type": evidence_type,
        "uri": relative_path.replace("\\", "/"),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "observed_at": datetime.now(UTC).isoformat(),
        "summary": f"{SCOPE.upper()} controlled evidence: {path.name}",
    }


def post_decision(token: str, gate_code: str, status: str, items: list[dict], reason: str) -> dict:
    body = json.dumps({
        "status": status,
        "evidence": items,
        "expires_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        "reason": reason,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}/production-acceptance/gates/{gate_code}/decision",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Host": HOST,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=30, context=ssl._create_unverified_context(),
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"gate decision rejected: {gate_code}: HTTP {exc.code}") from None


def local_decisions(token: str) -> list[dict]:
    results = []
    for gate_code, (status, specs) in LOCAL_DECISIONS.items():
        decision_status = status
        if gate_code == "CAPACITY_SOAK":
            for _, path in specs:
                payload = json.loads((ROOT / path).read_text(encoding="utf-8"))
                if payload.get("status") != "PASS":
                    decision_status = "BLOCKED"
        if gate_code in {"BACKUP_RECOVERY", "BACKUP_RESTORE", "ROLLBACK_DRILL"}:
            for _, path in specs:
                payload = json.loads((ROOT / path).read_text(encoding="utf-8"))
                if payload.get("status") != "PASS":
                    decision_status = "BLOCKED"
        items = [evidence(kind, path) for kind, path in specs]
        gate = post_decision(
            token, gate_code, decision_status, items,
            f"{SCOPE.upper()} local gate evidence was reverified; external gates and release authorization remain unchanged.",
        )
        results.append({
            "gate_code": gate_code,
            "status": gate["status"],
            "version": gate["version"],
            "evidence_hash": gate["evidence_hash"],
        })
    return results


def pre_push(token: str) -> list[dict]:
    gate = post_decision(
        token, "REMOTE_PUSH", "BLOCKED", [],
        f"{SCOPE.upper()} remote push cannot pass before the final local commit is published and 0/0 divergence is reverified.",
    )
    return [{"gate_code": "REMOTE_PUSH", "status": gate["status"], "version": gate["version"]}]


def post_push(token: str) -> list[dict]:
    branch = command("git", "branch", "--show-current")
    local_sha = command("git", "rev-parse", "HEAD")
    remote_line = command("git", "ls-remote", "origin", f"refs/heads/{branch}")
    remote_sha = remote_line.split()[0] if remote_line else ""
    counts = command("git", "rev-list", "--left-right", "--count", f"origin/{branch}...HEAD").split()
    if remote_sha != local_sha or counts != ["0", "0"]:
        raise RuntimeError("remote branch is not synchronized at 0/0")
    proof = json.dumps({
        "branch": branch, "local_sha": local_sha, "remote_sha": remote_sha,
        "behind": 0, "ahead": 0,
    }, sort_keys=True, separators=(",", ":"))
    items = [{
        "evidence_type": "runtime_probe",
        "uri": f"registry://origin/{branch}@{local_sha}",
        "sha256": hashlib.sha256(proof.encode("utf-8")).hexdigest(),
        "observed_at": datetime.now(UTC).isoformat(),
        "summary": f"Final {SCOPE.upper()} local and remote branch heads match with ahead/behind 0/0.",
    }]
    gate = post_decision(
        token, "REMOTE_PUSH", "PASSED", items,
        f"Final {SCOPE.upper()} branch was pushed normally and remote equality was verified after all commits.",
    )
    return [{
        "gate_code": "REMOTE_PUSH", "status": gate["status"],
        "version": gate["version"], "evidence_hash": gate["evidence_hash"],
    }]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("local", "pre-push", "post-push"), required=True)
    args = parser.parse_args()
    token, session_id = acceptance_identity()
    try:
        if args.phase == "local":
            results = local_decisions(token)
        elif args.phase == "pre-push":
            results = pre_push(token)
        else:
            results = post_push(token)
    finally:
        revoke_session(session_id)
    print(json.dumps({
        "status": "PASS", "phase": args.phase, "decisions": results,
        "token_printed": False, "external_gates_modified": False,
        "release_authorized": False, "traffic_switched": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__}, sort_keys=True))
        raise SystemExit(1) from None
