from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dashboard import validate_range
from app.api.dependencies import current_user
from app.core.database import get_db
from app.models.auth import User
from app.services.revenue import RevenueAnalysisService


router = APIRouter(prefix="/revenue", tags=["revenue"])


@router.get("/analysis")
def analysis(
    start: date,
    end_exclusive: date,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    validate_range(start, end_exclusive)
    return RevenueAnalysisService(db, user).analysis(start, end_exclusive)
