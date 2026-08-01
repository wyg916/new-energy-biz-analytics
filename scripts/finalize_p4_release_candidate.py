"""Create the single governed P4 preproduction release candidate.

This command is intentionally fail-closed.  It will not create a release until
the persisted acceptance evidence is complete, the 30-minute soak is the latest
capacity result, and the manifest explicitly keeps production authorization
disabled.  ``--activate`` is an explicit operator action; without it the script
only validates the candidate inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import desc, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.governance.contracts import GovernanceStatus
from app.governance.identity import IdentityService
from app.governance.models import PlatformRelease
from app.governance.release import ReleaseRegistry
from app.preproduction.models import PreproductionAcceptanceRecord


REQUIRED_PASS_CATEGORIES = {
    "OIDC_INTEGRATION",
    "SECRET_PROVIDER",
    "DATASOURCE_GOVERNANCE",
    "CAPACITY_SOAK",
    "FAILURE_RECOVERY",
    "BACKUP_RESTORE",
    "SECURITY_NEGATIVE",
    "FRONTEND_E2E",
    "FULL_REGRESSION",
}
REQUIRED_MANIFEST_FIELDS = {
    "schema_version",
    "version",
    "git_sha",
    "environment",
    "production_release_authorized",
    "image_digests",
    "migration_head",
    "config_template",
    "scenario_packages",
    "semantic_models",
    "rag_release",
    "skill_procedure_releases",
    "policy_bundle",
    "sqlbot_source_binding",
    "sbom",
    "security_scan",
    "test_matrix",
    "known_risks",
    "rollback_steps",
    "startup_steps",
    "acceptance_steps",
    "production_gates",
}


def _manifest(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    missing = sorted(REQUIRED_MANIFEST_FIELDS - payload.keys())
    if missing:
        raise RuntimeError(f"RC manifest is missing fields: {', '.join(missing)}")
    if payload["environment"] != "preproduction":
        raise RuntimeError("RC manifest environment must be preproduction")
    if payload["production_release_authorized"] is not False:
        raise RuntimeError("RC manifest must keep production_release_authorized=false")
    if payload["migration_head"] != "p4_0001":
        raise RuntimeError("RC manifest migration head must be p4_0001")
    git_sha = str(payload["git_sha"])
    if len(git_sha) != 40 or any(char not in "0123456789abcdef" for char in git_sha.lower()):
        raise RuntimeError("RC manifest git_sha must be a full hexadecimal commit")
    return payload, hashlib.sha256(raw).hexdigest()


def _latest_acceptance(db) -> dict[str, PreproductionAcceptanceRecord]:
    records = list(db.scalars(select(PreproductionAcceptanceRecord).where(
        PreproductionAcceptanceRecord.environment == "preproduction",
    ).order_by(desc(PreproductionAcceptanceRecord.finished_at))).all())
    latest: dict[str, PreproductionAcceptanceRecord] = {}
    for record in records:
        latest.setdefault(record.category, record)
    return latest


def _validate_acceptance(latest: dict[str, PreproductionAcceptanceRecord]) -> None:
    failures = [
        f"{category}={latest.get(category).status if latest.get(category) else 'MISSING'}"
        for category in sorted(REQUIRED_PASS_CATEGORIES)
        if latest.get(category) is None or latest[category].status != "PASS"
    ]
    sqlbot = latest.get("SQLBOT_EXTERNAL")
    if sqlbot is None or sqlbot.status != "CONDITIONAL":
        failures.append(f"SQLBOT_EXTERNAL={sqlbot.status if sqlbot else 'MISSING'}")
    else:
        metrics = json.loads(sqlbot.metrics_json or "{}")
        if int(metrics.get("actual_external_requests", -1)) != 0:
            failures.append("SQLBOT_EXTERNAL.actual_external_requests!=0")
    capacity = latest.get("CAPACITY_SOAK")
    if capacity is not None:
        metrics = json.loads(capacity.metrics_json or "{}")
        if int(metrics.get("configured_duration_seconds", 0)) < 1800:
            failures.append("CAPACITY_SOAK.configured_duration_seconds<1800")
    if failures:
        raise RuntimeError("P4 acceptance is incomplete: " + "; ".join(failures))


def _record_acceptance(db, release: PlatformRelease, manifest_hash: str) -> str:
    run_id = f"P4-RC-{release.version}"
    metrics = {
        "release_id": release.release_id,
        "version": release.version,
        "status": release.status,
        "environment": release.environment,
        "artifact_hash": manifest_hash,
        "production_release_authorized": False,
        "data_classification": "simulated",
        "period_start": "2025-01-01",
        "period_end_inclusive": "2026-06-30",
        "secret_values_exposed": False,
    }
    serialized = json.dumps(metrics, ensure_ascii=False, sort_keys=True)
    evidence_hash = hashlib.sha256(serialized.encode()).hexdigest()
    now = datetime.now(UTC)
    record = db.scalar(select(PreproductionAcceptanceRecord).where(
        PreproductionAcceptanceRecord.run_id == run_id,
        PreproductionAcceptanceRecord.category == "RELEASE_CANDIDATE",
    ))
    if record is None:
        record = PreproductionAcceptanceRecord(
            acceptance_id="ACC-" + hashlib.sha256(f"{run_id}:RELEASE_CANDIDATE".encode()).hexdigest()[:36],
            run_id=run_id,
            category="RELEASE_CANDIDATE",
            status="PASS",
            environment="preproduction",
            metrics_json=serialized,
            evidence_hash=evidence_hash,
            data_classification="simulated",
            started_at=now,
            finished_at=now,
            created_by=release.activated_by or "system:p4-rc",
        )
        db.add(record)
    else:
        record.status = "PASS"
        record.metrics_json = serialized
        record.evidence_hash = evidence_hash
        record.finished_at = now
    db.commit()
    return evidence_hash


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    manifest, manifest_hash = _manifest(args.manifest)
    settings = get_settings()
    if settings.app_env != "preproduction" or settings.production_release_authorized:
        raise RuntimeError("RC finalization requires preproduction with production release disabled")

    with SessionLocal() as db:
        latest = _latest_acceptance(db)
        _validate_acceptance(latest)
        existing = list(db.scalars(select(PlatformRelease).where(
            PlatformRelease.object_type == "RELEASE_CANDIDATE",
            PlatformRelease.object_id == "chatbi-p4",
            PlatformRelease.environment == "preproduction",
        ).order_by(PlatformRelease.created_at)).all())
        if len(existing) > 1:
            raise RuntimeError("more than one P4 release candidate exists")
        release = existing[0] if existing else None
        if release is not None and (release.version != manifest["version"] or release.artifact_hash != manifest_hash):
            raise RuntimeError("existing P4 release candidate does not match this immutable manifest")

        if args.activate:
            identity = IdentityService(db).resolve_oidc_session(
                principal_id="PRN-P4-OIDC-ANALYST",
                groups=("analysts",),
                request_id=f"P4-RC-{manifest['version']}",
            )
            registry = ReleaseRegistry(db, identity)
            if release is None:
                release = registry.create(
                    object_type="RELEASE_CANDIDATE",
                    object_id="chatbi-p4",
                    version=manifest["version"],
                    environment="preproduction",
                    artifact_hash=manifest_hash,
                    change_summary="P4 preproduction release candidate; production remains disabled",
                    metadata={
                        "git_sha": manifest["git_sha"],
                        "migration_head": manifest["migration_head"],
                        "manifest_schema": manifest["schema_version"],
                        "production_release_authorized": False,
                    },
                )
            if release.status == GovernanceStatus.DRAFT:
                release = registry.submit_review(release.release_id)
            if release.status == GovernanceStatus.REVIEW:
                release = registry.approve(release.release_id)
            if release.status == GovernanceStatus.APPROVED:
                release = registry.activate(release.release_id)
            if release.status != GovernanceStatus.ACTIVE:
                raise RuntimeError(f"P4 release candidate is not ACTIVE: {release.status}")
            evidence_hash = _record_acceptance(db, release, manifest_hash)
        else:
            evidence_hash = None

    print(json.dumps({
        "status": "ACTIVE" if release is not None and release.status == GovernanceStatus.ACTIVE else "VALIDATED",
        "release_id": release.release_id if release is not None else None,
        "version": manifest["version"],
        "environment": "preproduction",
        "manifest_hash": manifest_hash,
        "acceptance_evidence_hash": evidence_hash,
        "production_release_authorized": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
