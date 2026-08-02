"""Run Trivy against every P5A running or explicitly disabled image role."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "platformization" / "p5a" / "evidence" / "container-security"
TRIVY_IMAGE = "aquasec/trivy:0.70.0"
TRIVY_CACHE = "renewable-p5a-remediation_trivy_cache"
IMAGES = (
    ("api", "renewable-p5a-api:5.0.0-p5a", True),
    ("web", "renewable-p5a-web:5.0.0-p5a", True),
    ("postgresql", "renewable-p5a-postgres:16.14", True),
    ("redis", "redis:7.4.10-alpine@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2", True),
    ("nginx", "nginx:1.31.3-alpine@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752", True),
    ("keycloak", "renewable-p5a-keycloak:26.7.0", True),
    ("vault", "hashicorp/vault:2.0.3", True),
    ("sqlbot", "dataease/sqlbot:v1.8.0@sha256:c4ca3acc34f0c63a64f3f3e7bb909760f17d184959635542278710144347d9e0", False),
    ("alert-receiver", "renewable-p5a-alert-receiver:5.0.0-p5a", True),
    ("migration", "renewable-p5a-migration:5.0.0-p5a", True),
    ("backup", "renewable-p5a-backup:16.14", True),
)


def run(*args: str, capture: bool = False) -> str:
    process = subprocess.run(
        list(args),
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=capture,
    )
    if process.returncode:
        detail = (process.stderr or process.stdout).strip() if capture else ""
        raise RuntimeError(detail or f"command failed: {args[:3]}")
    return process.stdout.strip() if capture else ""


def image_identity(reference: str) -> dict:
    payload = json.loads(run("docker", "image", "inspect", reference, capture=True))[0]
    repo_digests = sorted(payload.get("RepoDigests") or [])
    return {
        "requested_reference": reference,
        "image_id": payload["Id"],
        "repo_digests": repo_digests,
        "content_digest": repo_digests[0].split("@", 1)[1] if repo_digests else payload["Id"],
    }


def vulnerabilities(payload: dict) -> list[dict]:
    items: list[dict] = []
    for result in payload.get("Results") or []:
        for vuln in result.get("Vulnerabilities") or []:
            items.append({
                "cve": vuln.get("VulnerabilityID"),
                "severity": vuln.get("Severity"),
                "package": vuln.get("PkgName"),
                "installed_version": vuln.get("InstalledVersion"),
                "fixed_version": vuln.get("FixedVersion") or "",
                "target": result.get("Target"),
                "class": result.get("Class"),
                "type": result.get("Type"),
            })
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    run("docker", "volume", "create", TRIVY_CACHE)
    trivy_version = run("docker", "run", "--rm", TRIVY_IMAGE, "--version", capture=True)
    started_at = datetime.now(UTC)
    entries = []
    scan_cache: dict[str, tuple[str, bytes]] = {}
    for role, reference, runtime_enabled in IMAGES:
        identity = image_identity(reference)
        raw_name = f"trivy-{role}.json"
        raw_path = output_dir / raw_name
        cached = scan_cache.get(identity["image_id"])
        if cached is None:
            run(
                "docker", "run", "--rm",
                "-v", "/var/run/docker.sock:/var/run/docker.sock",
                "-v", f"{TRIVY_CACHE}:/root/.cache/trivy",
                "-v", f"{output_dir}:/out",
                TRIVY_IMAGE,
                "image", "--scanners", "vuln", "--timeout", "60m",
                "--skip-version-check", "--format", "json",
                "--output", f"/out/{raw_name}", reference,
            )
            raw_bytes = raw_path.read_bytes()
            scan_cache[identity["image_id"]] = (role, raw_bytes)
            scan_execution = "EXECUTED"
            identical_to_role = None
        else:
            identical_to_role, raw_bytes = cached
            raw_path.write_bytes(raw_bytes)
            scan_execution = "REUSED_IDENTICAL_IMAGE_ID"
        raw = json.loads(raw_bytes)
        findings = vulnerabilities(raw)
        severity_counts = {
            severity: sum(item["severity"] == severity for item in findings)
            for severity in ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")
        }
        cves = sorted({item["cve"] for item in findings if item["cve"]})
        entries.append({
            "role": role,
            "runtime_enabled": runtime_enabled,
            **identity,
            "scan_completed_at": datetime.now(UTC).isoformat(),
            "trivy_version": trivy_version,
            "scan_execution": scan_execution,
            "identical_image_scan_role": identical_to_role,
            "critical": severity_counts["CRITICAL"],
            "high": severity_counts["HIGH"],
            "unique_cve_count": len(cves),
            "severity_counts": severity_counts,
            "affected_packages": findings,
            "raw_evidence": raw_name,
            "raw_evidence_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "status": "PASS" if not severity_counts["CRITICAL"] and not severity_counts["HIGH"] else "BLOCKED_NO_WAIVER",
        })

    summary = {
        "evidence_type": "p5a_container_security_rescan",
        "environment": "P5A production-acceptance, not production",
        "data_classification": "simulated",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "trivy_image": TRIVY_IMAGE,
        "trivy_version": trivy_version,
        "ignored_vulnerabilities": 0,
        "severity_lowering_applied": False,
        "waivers_created": 0,
        "images": entries,
        "totals": {
            "roles_scanned": len(entries),
            "unique_image_ids_scanned": len(scan_cache),
            "critical": sum(item["critical"] for item in entries),
            "high": sum(item["high"] for item in entries),
            "blocked_roles": [item["role"] for item in entries if item["status"] != "PASS"],
        },
        "image_security_gate": "PASSED" if all(item["status"] == "PASS" for item in entries) else "BLOCKED",
        "production_release_authorized": False,
        "production_traffic_switched": False,
    }
    serialized = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    summary_path = output_dir / "container-security-summary.json"
    summary_path.write_text(serialized, encoding="utf-8")
    print(json.dumps({
        "status": summary["image_security_gate"],
        "roles_scanned": len(entries),
        "critical": summary["totals"]["critical"],
        "high": summary["totals"]["high"],
        "summary_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }, sort_keys=True))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
