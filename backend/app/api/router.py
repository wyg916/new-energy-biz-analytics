from fastapi import APIRouter

from app.api.auth import router as auth_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)


@api_router.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "service": "alpha-api", "data_classification": "simulated"}
