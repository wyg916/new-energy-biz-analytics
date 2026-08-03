"""Create the P5A dependency inventory and the unique local RC manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "platformization" / "p5a" / "evidence"
INVENTORY = EVIDENCE / "p5a-dependency-inventory.json"
MANIFEST = EVIDENCE / "p5a-rc-4.0.0-rc.2-manifest.json"
IMAGES = {
    "api": ("renewable-p5a-api:5.0.0-p5a", True),
    "web": ("renewable-p5a-web:5.0.0-p5a", True),
    "postgresql": ("renewable-p5a-postgres:16.14", True),
    "redis": ("redis:7.4.10-alpine@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2", True),
    "nginx": ("nginx:1.31.3-alpine@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752", True),
    "keycloak": ("renewable-p5a-keycloak:26.7.0", True),
    "vault": ("hashicorp/vault:2.0.3", True),
    "alert_receiver": ("renewable-p5a-alert-receiver:5.0.0-p5a", True),
    "migration": ("renewable-p5a-migration:5.0.0-p5a", True),
    "backup": ("renewable-p5a-backup:16.14", True),
    "sqlbot": ("dataease/sqlbot:v1.8.0@sha256:c4ca3acc34f0c63a64f3f3e7bb909760f17d184959635542278710144347d9e0", False),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(*args: str) -> str:
    process = subprocess.run(
        list(args), cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
    )
    if process.returncode:
        raise RuntimeError(f"release candidate command failed safely: {args[:3]}")
    return process.stdout.strip()


def image_inventory() -> dict:
    result = {}
    for role, (reference, included) in IMAGES.items():
        payload = json.loads(command("docker", "image", "inspect", reference))[0]
        repo_digests = sorted(payload.get("RepoDigests") or [])
        result[role] = {
            "reference": reference,
            "image_id": payload["Id"],
            "repo_digests": repo_digests,
            "content_digest": repo_digests[0].split("@", 1)[1] if repo_digests else payload["Id"],
            "included_in_rc": included,
            "runtime_enabled": included,
        }
    result["sqlbot"]["runtime_enabled"] = False
    return result


def artifact(relative: str, status: str | None = None) -> dict:
    path = ROOT / relative
    item = {"path": relative.replace("\\", "/"), "sha256": sha(path)}
    if status is not None:
        item["status"] = status
    return item


def write_inventory() -> None:
    if INVENTORY.exists():
        raise RuntimeError("refusing to overwrite dependency inventory")
    sbom = EVIDENCE / "p5a-sbom.cdx.json"
    payload = {
        "schema_version": "1.0",
        "evidence_type": "p5a_dependency_and_image_inventory",
        "captured_at": datetime.now(UTC).isoformat(),
        "environment": "local_preproduction",
        "dependency_manifests": {
            "backend_lock": artifact("backend/requirements.lock"),
            "backend_project": artifact("backend/pyproject.toml"),
            "frontend_lock": artifact("frontend/package-lock.json"),
        },
        "sbom": {
            "format": "CycloneDX",
            "generator": "Trivy 0.70.0 filesystem vulnerability inventory",
            "path": "docs/platformization/p5a/evidence/p5a-sbom.cdx.json",
            "sha256": sha(sbom),
            "env_files_excluded": True,
        },
        "images": image_inventory(),
        "actual_runtime_components": [
            "api", "web", "postgresql", "redis", "nginx", "keycloak", "vault",
            "alert_receiver", "migration", "backup",
        ],
        "excluded_components": ["sqlbot"],
        "status": "COMPLETE_LOCAL_PREPRODUCTION_INVENTORY",
        "production_release_authorized": False,
    }
    INVENTORY.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "phase": "inventory", "images": len(payload["images"])}))


def write_manifest(source_git_sha: str) -> None:
    if MANIFEST.exists():
        raise RuntimeError("refusing to overwrite RC manifest")
    if command("git", "rev-parse", "HEAD") != source_git_sha:
        raise RuntimeError("source Git SHA must equal current HEAD")
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    scan = json.loads((EVIDENCE / "container-security" / "container-security-summary.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": "1.0",
        "rc_version": "4.0.0-rc.2",
        "source_git_sha": source_git_sha,
        "branch": command("git", "branch", "--show-current"),
        "environment": "local_preproduction",
        "data": {
            "classification": "simulated",
            "period_start": "2025-01-01",
            "period_end": "2026-06-30",
            "capacity_run_id": "P5-CAP-20260802T173756Z",
        },
        "alembic_head": "p5_0001",
        "images": inventory["images"],
        "actual_runtime_components": inventory["actual_runtime_components"],
        "sqlbot": {
            "adapter": "PASS", "offline_contract": "PASS", "runtime": "DISABLED",
            "image_security": "BLOCKED", "external_eval": "CONDITIONAL",
            "canary": False, "included_in_rc": False,
        },
        "sbom": inventory["sbom"],
        "dependency_inventory": artifact("docs/platformization/p5a/evidence/p5a-dependency-inventory.json"),
        "security_scan": {
            **artifact("docs/platformization/p5a/evidence/container-security/container-security-summary.json", "BLOCKED"),
            "roles_scanned": scan["totals"]["roles_scanned"],
            "unique_image_ids": scan["totals"]["unique_image_ids_scanned"],
            "critical_by_role": scan["totals"]["critical"],
            "high_by_role": scan["totals"]["high"],
            "waivers": scan["waivers_created"],
        },
        "acceptance_evidence": {
            "postgresql_regression": artifact("docs/platformization/p5a/evidence/p5a-final-regression-summary.json", "PASS"),
            "playwright_23": artifact("docs/platformization/p5a/evidence/playwright-original-23-p5a-final.xml", "PASS"),
            "playwright_oidc_3": artifact("docs/platformization/p5a/evidence/playwright-p4-oidc-3-p5a-final.xml", "PASS"),
            "playwright_gate_1": artifact("docs/platformization/p5a/evidence/playwright-p5-gate-1-p5a-contract-rerun.xml", "PASS"),
            "docker_smoke": artifact("docs/platformization/p5a/evidence/docker-smoke-p5a-final.json", "PASS"),
            "capacity_two_hour": artifact("docs/platformization/p5a/evidence/p5a-capacity-verification.json", "PASS"),
            "failure_recovery": artifact("docs/platformization/p5a/evidence/p5a-fault-recovery.json", "PASS"),
            "backup_restore": artifact("docs/platformization/p5a/evidence/p5a-backup-restore.json", "PASS"),
            "gate_snapshot": artifact("docs/platformization/p5a/evidence/p5a-gate-snapshot-pre-push.json", "PASS"),
        },
        "rag": {"runtime_mode": "KEYWORD_ONLY", "vector_released": False},
        "unclosed_external_gates": {
            "count": 15,
            **artifact("docs/platformization/p5a/12_UNRESOLVED_EXTERNAL_GATES.md", "OPEN_CONDITIONAL"),
        },
        "rollback": {
            **artifact("docs/platformization/p5a/08_FAILURE_BACKUP_AND_RECOVERY.md"),
            "strategy": "revert independent P5A commits in reverse order; preserve volumes; no force push",
        },
        "local_preproduction_rc": "PASS_WITH_BLOCKED_PRODUCTION_GATES",
        "production_acceptance_ready": False,
        "production_release_authorized": False,
        "production_traffic_switched": False,
        "sqlbot_canary_eligible": False,
        "go_no_go": "NO_GO",
    }
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS", "phase": "manifest", "rc_version": payload["rc_version"],
        "manifest_sha256": sha(MANIFEST), "production_release_authorized": False,
    }, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("inventory", "manifest"), required=True)
    parser.add_argument("--source-git-sha")
    args = parser.parse_args()
    if args.phase == "inventory":
        write_inventory()
    elif not args.source_git_sha:
        parser.error("--source-git-sha is required for manifest")
    else:
        write_manifest(args.source_git_sha)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
