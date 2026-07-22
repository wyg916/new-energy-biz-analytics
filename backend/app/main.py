from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.bootstrap import bootstrap_demo_users
from app.core.config import get_settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    settings = get_settings()
    if settings.auto_bootstrap_demo_users and settings.app_env != "production":
        bootstrap_demo_users()
    yield


app = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": "请求参数不合法", "details": exc.errors()}})
