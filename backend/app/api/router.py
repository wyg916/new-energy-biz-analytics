from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.chatbi import router as chatbi_router
from app.api.diagnostics import router as diagnostics_router
from app.api.reports import router as reports_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(dashboard_router)
api_router.include_router(chatbi_router)
api_router.include_router(diagnostics_router)
api_router.include_router(reports_router)


@api_router.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "service": "alpha-api", "data_classification": "simulated"}
