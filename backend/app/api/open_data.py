import json
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.core.database import get_db
from app.data.open_source import lineage_status
from app.models.auth import AuditLog, User
from app.models.open_data import OpenDataQualityCheck


router = APIRouter(prefix="/data/open-source", tags=["open-source-data"])


@router.get("/status")
def status(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    lineage = lineage_status(db)
    pass_count = int(db.scalar(
        select(func.count()).select_from(OpenDataQualityCheck).where(OpenDataQualityCheck.status == "PASS")
    ) or 0)
    fail_count = int(db.scalar(
        select(func.count()).select_from(OpenDataQualityCheck).where(OpenDataQualityCheck.status == "FAIL")
    ) or 0)
    lineage["quality"] = {
        "status": "PASS" if pass_count >= 28 and fail_count == 0 else "NOT_READY",
        "pass_count": pass_count,
        "fail_count": fail_count,
    }
    db.add(AuditLog(
        actor_user_id=user.id, action="open_data.status", resource="open_source_data",
        outcome="success", detail_json=json.dumps({"run_count": len(lineage["runs"]), "fail_count": fail_count}),
    ))
    db.commit()
    return lineage


@router.get("/schema-catalog")
def schema_catalog(_: User = Depends(current_user)) -> dict:
    container_path = Path("/app/docs/data/schema_catalog.json")
    path = container_path if container_path.is_file() else Path(__file__).resolve().parents[3] / "docs" / "data" / "schema_catalog.json"
    return json.loads(path.read_text(encoding="utf-8"))
