from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dashboard import validate_range
from app.api.dependencies import current_user
from app.core.database import get_db
from app.models.auth import User
from app.services.reports import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/draft")
def draft(report_type: str = Query("monthly", pattern="^(weekly|monthly)$"), start: date = Query(...), end_exclusive: date = Query(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    validate_range(start, end_exclusive)
    return ReportService(db, user).draft(report_type, start, end_exclusive)


@router.get("/export")
def export(report_type: str = Query("monthly", pattern="^(weekly|monthly)$"), format: str = Query("markdown", pattern="^(markdown|csv)$"), start: date = Query(...), end_exclusive: date = Query(...), db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    validate_range(start, end_exclusive)
    report = ReportService(db, user).draft(report_type, start, end_exclusive)
    if format == "csv":
        content = ReportService.csv_bytes(report); media_type = "text/csv; charset=utf-8"; suffix = "csv"
    else:
        content = report["markdown"].encode("utf-8"); media_type = "text/markdown; charset=utf-8"; suffix = "md"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f"attachment; filename=renewable-alpha-{report_type}.{suffix}", "X-Analysis-Run-Id": report["metadata"]["analysis_run_id"], "X-Data-Classification": "simulated"})
