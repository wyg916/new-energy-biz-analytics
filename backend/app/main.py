from contextlib import asynccontextmanager
import logging
import re
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.bootstrap import bootstrap_demo_users
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.observability import request_metrics
from app.governance.identity import TrustedIdentityMiddleware
from app.governance.authorization import AuthorizationDenied


logger = logging.getLogger("app.http")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    settings = get_settings()
    if settings.auto_bootstrap_demo_users and settings.app_env != "production":
        bootstrap_demo_users()
    yield


app = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_settings().trusted_host_list)
app.add_middleware(TrustedIdentityMiddleware)
app.include_router(api_router)


@app.middleware("http")
async def observe_request(request: Request, call_next):
    supplied_request_id = request.headers.get("x-request-id", "")
    request_id = supplied_request_id if REQUEST_ID_PATTERN.fullmatch(supplied_request_id) else f"REQ-{uuid4()}"
    started = perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration_seconds = perf_counter() - started
        request_metrics.observe(request.method, status_code, duration_seconds)
        logger.info(
            "http_request",
            extra={
                "context": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round(duration_seconds * 1000, 3),
                }
            },
        )


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": "请求参数不合法", "details": exc.errors()}})


@app.exception_handler(AuthorizationDenied)
async def authorization_denied(_: Request, exc: AuthorizationDenied) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"detail": {"code": exc.code, "message": str(exc)}},
    )
