from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.chatbi import router as chatbi_router
from app.api.diagnostics import router as diagnostics_router
from app.api.reports import router as reports_router
from app.api.revenue import router as revenue_router
from app.api.data_integration import router as data_integration_router
from app.api.platform_foundation import router as platform_foundation_router
from app.api.assistant import router as assistant_router
from app.knowledge.api import router as knowledge_router
from app.core.config import get_settings
from app.core.observability import readiness_snapshot, request_metrics

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(dashboard_router)
api_router.include_router(chatbi_router)
api_router.include_router(diagnostics_router)
api_router.include_router(reports_router)
api_router.include_router(revenue_router)
api_router.include_router(data_integration_router)
api_router.include_router(platform_foundation_router)
api_router.include_router(knowledge_router)
api_router.include_router(assistant_router)


@api_router.get("/health", tags=["system"])
def health() -> dict:
    return {
        "status": "ok",
        "service": "renewable-operations-api",
        "release_version": get_settings().release_version,
        "data_classification": "simulated",
    }


@api_router.get("/health/ready", tags=["system"])
def ready() -> JSONResponse:
    payload, status_code = readiness_snapshot()
    return JSONResponse(status_code=status_code, content=payload)


@api_router.get("/metrics", tags=["system"], include_in_schema=False)
def metrics() -> PlainTextResponse:
    return PlainTextResponse(
        request_metrics.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
