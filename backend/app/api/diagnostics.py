from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.api.dashboard import validate_range
from app.core.database import get_db
from app.models.auth import User
from app.services.diagnostics import DiagnosticService

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/decomposition")
def decomposition(metric: str, start: date, end_exclusive: date, comparison: str = Query("mom", pattern="^(mom|yoy)$"), limit: int = Query(5, ge=1, le=30), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    validate_range(start, end_exclusive)
    try: return DiagnosticService(db, user).decompose(metric, start, end_exclusive, comparison, limit)
    except ValueError as exc: raise HTTPException(status_code=422, detail={"code": "UNSUPPORTED_DIAGNOSTIC", "message": str(exc)})


@router.get("/anomalies")
def anomalies(metric: str, start: date, end_exclusive: date, threshold: float = Query(0.15, ge=0.05, le=1), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    validate_range(start, end_exclusive)
    try: return DiagnosticService(db, user).anomalies(metric, start, end_exclusive, threshold)
    except ValueError as exc: raise HTTPException(status_code=422, detail={"code": "UNKNOWN_METRIC", "message": str(exc)})


@router.get("/peer")
def peer(station_id: str, metric: str, start: date, end_exclusive: date, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    validate_range(start, end_exclusive)
    try: return DiagnosticService(db, user).peer_comparison(station_id, metric, start, end_exclusive)
    except PermissionError: raise HTTPException(status_code=403, detail={"code": "AUTH_SCOPE_DENIED", "message": "场站不在授权范围内"})
