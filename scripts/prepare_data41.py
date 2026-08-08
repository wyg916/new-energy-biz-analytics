"""Prepare the DATA-4.1 PostgreSQL database idempotently from committed snapshots."""

from __future__ import annotations

import json
import os

from sqlalchemy import func, select, text

from app.core.database import SessionLocal
from app.data.open_source import ingest_all
from app.models.business import DataGenerationRun
from app.models.open_data import OpenDataQualityCheck
from scripts.prepare_p4_preproduction import main as prepare_p4_baseline


EXPECTED_REVISION = os.getenv("EXPECTED_DATABASE_REVISION", "data_0001")


def main() -> None:
    with SessionLocal() as db:
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        has_fixture = db.scalar(select(func.count()).select_from(DataGenerationRun)) or 0
    if revision != EXPECTED_REVISION:
        raise RuntimeError(f"DATA-4.1 database must be at {EXPECTED_REVISION}, got {revision}")
    if not has_fixture:
        prepare_p4_baseline()
    with SessionLocal() as db:
        result = ingest_all(db)
        pass_count = int(db.scalar(
            select(func.count()).select_from(OpenDataQualityCheck).where(OpenDataQualityCheck.status == "PASS")
        ) or 0)
        fail_count = int(db.scalar(
            select(func.count()).select_from(OpenDataQualityCheck).where(OpenDataQualityCheck.status == "FAIL")
        ) or 0)
    result["revision"] = revision
    result["quality_check_pass_count"] = pass_count
    result["quality_check_fail_count"] = fail_count
    result["idempotent_initial_import"] = True
    result["source_download_on_startup"] = False
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
