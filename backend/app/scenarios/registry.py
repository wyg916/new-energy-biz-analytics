from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business import DataGenerationRun
from app.models.integration import ScenarioPackageRelease
from app.scenarios.charging_ops.manifest import (
    DISPLAY_NAME, MANIFEST_CHECKSUM, MANIFEST_JSON, SCENARIO_ID, VERSION,
)


def install_charging_ops(db: Session, source_batch_id: str | None = None, publish: bool = False) -> ScenarioPackageRelease:
    release = db.scalar(select(ScenarioPackageRelease).where(
        ScenarioPackageRelease.scenario_id == SCENARIO_ID,
        ScenarioPackageRelease.version == VERSION,
    ))
    now = datetime.now(UTC)
    if release is None:
        release = ScenarioPackageRelease(
            scenario_id=SCENARIO_ID, version=VERSION, display_name=DISPLAY_NAME,
            manifest_json=MANIFEST_JSON, manifest_checksum=MANIFEST_CHECKSUM,
            status="installed", installed_at=now,
        )
        db.add(release)
    if publish:
        release.status = "published"
        release.source_batch_id = source_batch_id
        release.published_at = now
    return release


def published_charging_ops(db: Session) -> ScenarioPackageRelease | None:
    return db.scalar(select(ScenarioPackageRelease).where(
        ScenarioPackageRelease.scenario_id == SCENARIO_ID,
        ScenarioPackageRelease.status.in_(("published", "PUBLISHED", "ACTIVE")),
        ScenarioPackageRelease.source_batch_id.is_not(None),
    ).order_by(ScenarioPackageRelease.published_at.desc()))


def published_charging_ops_batch(db: Session) -> DataGenerationRun | None:
    release = published_charging_ops(db)
    return db.get(DataGenerationRun, release.source_batch_id) if release and release.source_batch_id else None
