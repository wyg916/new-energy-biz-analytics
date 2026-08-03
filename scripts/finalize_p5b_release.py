"""Create the immutable P5B 4.0.0-rc.3 release manifest."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "platformization" / "p5b" / "evidence"
OUTPUT = EVIDENCE / "p5b-rc-4.0.0-rc.3-manifest.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    process = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
    )
    if process.returncode:
        raise RuntimeError(f"git command failed: {args[:2]}")
    return process.stdout.strip()


def evidence(path: str, status: str = "PASS") -> dict:
    target = ROOT / path
    if not target.is_file():
        raise RuntimeError(f"release evidence missing: {path}")
    return {"path": path, "sha256": sha(target), "status": status}


def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError("refusing to overwrite P5B RC manifest")
    security_path = EVIDENCE / "container-security" / "container-security-summary.json"
    security = json.loads(security_path.read_text(encoding="utf-8"))
    gate_path = EVIDENCE / "p5b-gate-snapshot-pre-push.json"
    gates = json.loads(gate_path.read_text(encoding="utf-8"))
    regression = json.loads((EVIDENCE / "p5b-final-regression-summary.json").read_text(encoding="utf-8"))
    sbom_path = EVIDENCE / "p5b-sbom.cdx.json"
    sbom_text = sbom_path.read_text(encoding="utf-8")
    if "sqlbot" in sbom_text.lower():
        raise RuntimeError("SQLBot is forbidden from the v4 release SBOM")

    images = {
        item["role"]: {
            "reference": item["reference"],
            "image_id": item["image_id"],
            "content_digest": item["content_digest"],
            "repo_digests": item["repo_digests"],
            "runtime_enabled": True,
            "included_in_rc": True,
            "critical": item["effective_critical"],
            "high": item["effective_high"],
            "security_status": item["status"],
        }
        for item in security["images"]
    }
    if "sqlbot" in images or len(images) != 10:
        raise RuntimeError("P5B RC image inventory must contain 10 non-SQLBot roles")

    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "release_candidate": "4.0.0-rc.3",
        "environment": "local_preproduction",
        "branch": git("branch", "--show-current"),
        "source_git_sha": git("rev-parse", "HEAD"),
        "alembic_head": "p5_0001",
        "data": {
            "classification": "simulated",
            "period_start": "2025-01-01",
            "period_end": "2026-06-30",
            "source": "fixed-seed business-rule simulation stored in PostgreSQL",
        },
        "runtime_contract": {
            "deterministic_engine": "ONLY_FORMAL_NL2SQL_EXECUTION_PATH",
            "rag_mode": "KEYWORD_ONLY",
            "sqlbot_runtime": "NOT_INCLUDED_IN_THIS_RELEASE",
            "sqlbot_image_in_bom": False,
            "sqlbot_image_in_sbom": False,
            "sqlbot_canary_eligible": False,
        },
        "actual_runtime_components": sorted(images),
        "images": images,
        "excluded_components": {
            "sqlbot": {
                "adapter_source_retained": True,
                "offline_contract": "PASS",
                "runtime": "NOT_INCLUDED",
                "external_evaluation": "DEFERRED",
                "original_scan_retained": {"critical": 49, "high": 802},
            }
        },
        "acceptance_evidence": {
            "regression": evidence("docs/platformization/p5b/evidence/p5b-final-regression-summary.json"),
            "docker_smoke": evidence("docs/platformization/p5b/evidence/docker-smoke-p5b-final.json"),
            "backup_restore": evidence("docs/platformization/p5b/evidence/p5b-backup-restore.json"),
            "failure_recovery": evidence("docs/platformization/p5b/evidence/p5b-fault-recovery.json"),
            "rollback_drill": evidence("docs/platformization/p5b/evidence/p5b-rollback-drill.json"),
            "container_security": evidence("docs/platformization/p5b/evidence/container-security/container-security-summary.json", security["local_rc_security"]),
            "gate_snapshot_pre_push": evidence("docs/platformization/p5b/evidence/p5b-gate-snapshot-pre-push.json"),
            "sbom": evidence("docs/platformization/p5b/evidence/p5b-sbom.cdx.json"),
        },
        "regression": regression,
        "security": {
            "roles_scanned": security["totals"]["roles_scanned"],
            "unique_image_ids_scanned": security["totals"]["unique_image_ids_scanned"],
            "critical": security["totals"]["effective_critical"],
            "high": security["totals"]["effective_high"],
            "waivers": security["waivers_created"],
            "status": security["local_rc_security"],
        },
        "gate_registry_pre_push": {
            "counts": gates["counts"],
            "unresolved_blockers": gates["unresolved_blockers"],
            "waivers": gates["waived_gate_codes"],
        },
        "sensitive_information_scan": {
            "path": "docs/platformization/p5b/evidence/p5b-secret-scan.json",
            "must_be_rerun_after_manifest_generation": True,
            "secret_values_recorded": False,
        },
        "local_preproduction_rc": "PASS_WITH_EXTERNAL_PRODUCTION_GATES",
        "p5b_implementation": "PASS",
        "production_acceptance_ready": False,
        "production_release_authorized": False,
        "production_traffic_switched": False,
        "go_no_go": "NO_GO",
        "p6_entry": "NOT_ALLOWED",
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS", "release_candidate": payload["release_candidate"],
        "images": len(images), "critical": payload["security"]["critical"],
        "high": payload["security"]["high"], "manifest_sha256": sha(OUTPUT),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
