from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.core.database import get_db
from app.models.auth import User
from app.services.metric_catalog import METRICS
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def validate_range(start: date, end_exclusive: date) -> None:
    if start >= end_exclusive:
        raise HTTPException(status_code=422, detail={"code": "INVALID_TIME_RANGE", "message": "开始日期必须早于结束日期"})
    if start < date(2025, 1, 1) or end_exclusive > date(2026, 7, 1):
        raise HTTPException(status_code=422, detail={"code": "OUT_OF_DATA_RANGE", "message": "查询超出模拟数据时间范围"})


@router.get("/summary")
def summary(start: date, end_exclusive: date, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    validate_range(start, end_exclusive)
    return DashboardService(db, user).summary(start, end_exclusive)


@router.get("/stations")
def stations(start: date, end_exclusive: date, metrics: str = Query("charging_revenue,gross_profit,gross_margin,charging_volume_kwh,station_utilization_rate,device_fault_rate"), limit: int = Query(30, ge=1, le=30), db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    validate_range(start, end_exclusive)
    metric_ids = [item.strip() for item in metrics.split(",") if item.strip()]
    if not metric_ids or set(metric_ids) - METRICS.keys():
        raise HTTPException(status_code=422, detail={"code": "UNKNOWN_METRIC", "message": "包含未批准指标"})
    return DashboardService(db, user).station_analysis(metric_ids, start, end_exclusive, limit)


@router.get("/trend")
def trend(metric: str, start: date, end_exclusive: date, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    validate_range(start, end_exclusive)
    if metric not in METRICS:
        raise HTTPException(status_code=422, detail={"code": "UNKNOWN_METRIC", "message": "指标未批准"})
    return DashboardService(db, user).monthly_trend(metric, start, end_exclusive)
