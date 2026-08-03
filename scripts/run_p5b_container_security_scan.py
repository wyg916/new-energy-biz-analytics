"""Scan every P5B RC image and preserve raw versus evidence-dispositioned counts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "platformization" / "p5b" / "evidence" / "container-security"
TRIVY_IMAGE = "aquasec/trivy:0.70.0"
TRIVY_CACHE = "renewable-p5b-gate-closure_trivy_cache"
IMAGES = (
    ("api", "renewable-p5b-api:4.0.0-rc.3"),
    ("web", "renewable-p5b-web:4.0.0-rc.3"),
    ("postgresql", "renewable-p5b-postgres:16.14-hardened"),
    ("redis", "redis:7.4.10-alpine@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2"),
    ("nginx", "nginx:1.31.3-alpine@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752"),
    ("keycloak", "renewable-p5b-keycloak:26.7.0-hardened"),
    ("vault", "hashicorp/vault:2.0.3@sha256:a296a888b118615dc01d5f1a6846e6d4a7277946caaed5b447008fff5fe06b54"),
    ("alert-receiver", "renewable-p5b-alert-receiver:4.0.0-rc.3"),
    ("migration", "renewable-p5b-migration:4.0.0-rc.3"),
    ("backup", "renewable-p5b-backup:16.14-hardened"),
)
KEYCLOAK_VERIFIED_NOT_AFFECTED = {
    "GHSA-r7wm-3cxj-wff9", "CVE-2026-54512", "CVE-2026-54513",
}


def run(*args: str, capture: bool = False) -> str:
    process = subprocess.run(
        list(args), cwd=ROOT, text=True, encoding="utf-8", capture_output=capture,
    )
    if process.returncode:
        detail = (process.stderr or process.stdout).strip() if capture else ""
        raise RuntimeError(detail or f"security scan command failed: {args[:3]}")
    return process.stdout.strip() if capture else ""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def findings(payload: dict) -> list[dict]:
    result: list[dict] = []
    for target in payload.get("Results") or []:
        for item in target.get("Vulnerabilities") or []:
            result.append({
                "cve": item.get("VulnerabilityID"),
                "severity": item.get("Severity"),
                "package": item.get("PkgName"),
                "installed_version": item.get("InstalledVersion"),
                "fixed_version": item.get("FixedVersion") or "",
                "target": target.get("Target"),
                "class": target.get("Class"),
                "type": target.get("Type"),
            })
    return result


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    run("docker", "volume", "create", TRIVY_CACHE)
    version = run("docker", "run", "--rm", TRIVY_IMAGE, "--version", capture=True)
    started = datetime.now(UTC)
    scans: dict[str, tuple[str, bytes]] = {}
    entries = []
    for role, reference in IMAGES:
        identity = json.loads(run("docker", "image", "inspect", reference, capture=True))[0]
        image_id = identity["Id"]
        raw_path = OUTPUT / f"trivy-{role}.json"
        if image_id in scans:
            reused_role, raw_bytes = scans[image_id]
            raw_path.write_bytes(raw_bytes)
            execution = "REUSED_IDENTICAL_IMAGE_ID"
        else:
            reused_role = None
            run(
                "docker", "run", "--rm",
                "-v", "/var/run/docker.sock:/var/run/docker.sock",
                "-v", f"{TRIVY_CACHE}:/root/.cache/trivy",
                "-v", f"{OUTPUT}:/out", TRIVY_IMAGE,
                "image", "--scanners", "vuln", "--timeout", "60m",
                "--skip-version-check", "--format", "json",
                "--output", f"/out/{raw_path.name}", reference,
            )
            raw_bytes = raw_path.read_bytes()
            scans[image_id] = (role, raw_bytes)
            execution = "EXECUTED"
        items = findings(json.loads(raw_bytes))
        raw_critical = sum(item["severity"] == "CRITICAL" for item in items)
        raw_high = sum(item["severity"] == "HIGH" for item in items)
        dispositions = []
        if role == "keycloak":
            dispositions = [
                {"cve": item["cve"], "disposition": "VERIFIED_NOT_AFFECTED_ACTUAL_JAR_2.21.4"}
                for item in items if item["cve"] in KEYCLOAK_VERIFIED_NOT_AFFECTED
            ]
        disposed_ids = {item["cve"] for item in dispositions}
        effective = [item for item in items if item["cve"] not in disposed_ids]
        effective_critical = sum(item["severity"] == "CRITICAL" for item in effective)
        effective_high = sum(item["severity"] == "HIGH" for item in effective)
        if not effective_critical and not effective_high:
            status = "PASS" if not dispositions else "PASS_WITH_VERIFIED_NOT_AFFECTED"
        elif not effective_critical and all(not item["fixed_version"] for item in effective if item["severity"] == "HIGH"):
            status = "BLOCKED_UPSTREAM_FIX_UNAVAILABLE"
        else:
            status = "BLOCKED"
        repo_digests = sorted(identity.get("RepoDigests") or [])
        entries.append({
            "role": role, "reference": reference, "included_in_rc": True,
            "image_id": image_id, "repo_digests": repo_digests,
            "content_digest": repo_digests[0].split("@", 1)[1] if repo_digests else image_id,
            "scan_execution": execution, "identical_image_scan_role": reused_role,
            "raw_critical": raw_critical, "raw_high": raw_high,
            "effective_critical": effective_critical, "effective_high": effective_high,
            "dispositions": dispositions, "affected_packages": items,
            "raw_evidence": raw_path.name, "raw_evidence_sha256": sha(raw_path),
            "status": status,
        })
    summary = {
        "schema_version": "1.0", "evidence_type": "p5b_container_security_rescan",
        "environment": "P5B local preproduction, not production",
        "started_at": started.isoformat(), "finished_at": datetime.now(UTC).isoformat(),
        "trivy_image": TRIVY_IMAGE, "trivy_version": version,
        "ignored_vulnerabilities": 0, "severity_lowering_applied": False,
        "waivers_created": 0, "images": entries,
        "totals": {
            "roles_scanned": len(entries), "unique_image_ids_scanned": len(scans),
            "raw_critical": sum(item["raw_critical"] for item in entries),
            "raw_high": sum(item["raw_high"] for item in entries),
            "effective_critical": sum(item["effective_critical"] for item in entries),
            "effective_high": sum(item["effective_high"] for item in entries),
            "blocked_roles": [item["role"] for item in entries if item["status"].startswith("BLOCKED")],
        },
        "keycloak_component_verification": {
            "path": "keycloak-component-verification.json",
            "sha256": sha(OUTPUT / "keycloak-component-verification.json"),
            "waiver": False,
        },
        "sqlbot": {
            "included_in_release": False, "included_in_scan_inventory": False,
            "original_scan_preserved": "docs/platformization/p5a/evidence/container-security/trivy-sqlbot.json",
            "original_critical": 49, "original_high": 802,
        },
        "local_rc_security": "PASS_NO_UNDISPOSITIONED_CRITICAL" if not sum(item["effective_critical"] for item in entries) else "BLOCKED_CRITICAL",
        "production_release_authorized": False, "production_traffic_switched": False,
    }
    rendered = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output = OUTPUT / "container-security-summary.json"
    output.write_text(rendered, encoding="utf-8")
    print(json.dumps({"status": summary["local_rc_security"], **summary["totals"], "summary_sha256": sha(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
