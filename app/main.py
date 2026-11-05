"""FastAPI application: middleware, routers, error handling, static SPA."""

from __future__ import annotations

import logging
import os
import uuid

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import init_db
from app.engine.analyze import ENGINE_NAME, ENGINE_VERSION
from app.engine.report import DISCLAIMER
from app.ratelimit import Limit, RateLimiter
from app.routers import analysis, auth, health, reports, studies

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("tashkhees")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Path-prefix → limit. Longest matching prefix wins.
RATE_LIMITS: tuple[tuple[str, str], ...] = (
    ("/api/auth", settings.rate_limit_auth),
    ("/api/analysis", settings.rate_limit_analysis),
    ("/api", settings.rate_limit_default),
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(self)",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def _limit_for(path: str) -> Limit | None:
    best: tuple[int, str] | None = None
    for prefix, spec in RATE_LIMITS:
        if path.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), spec)
    return Limit.parse(best[1]) if best else None


def create_app() -> FastAPI:
    problems = settings.validate()
    if problems:
        raise RuntimeError("Invalid configuration: " + "; ".join(problems))

    app = FastAPI(
        title=f"{settings.app_name} API",
        description=(
            "AI-assisted chest radiograph measurement and reporting. "
            "NOT a medical device — engineering demonstration only."
        ),
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    app.state.limiter = RateLimiter()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_and_limits(request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        limit = _limit_for(request.url.path)
        if limit is not None:
            client = request.client.host if request.client else "unknown"
            allowed, retry_after = app.state.limiter.check(f"{client}:{request.url.path}", limit)
            if not allowed:
                response = JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": "rate_limited",
                        "detail": "Too many requests. Please slow down.",
                        "request_id": request_id,
                    },
                )
                response.headers["Retry-After"] = str(int(retry_after) + 1)
                for k, v in SECURITY_HEADERS.items():
                    response.headers[k] = v
                return response

        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers[k] = v
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "http_error",
                "detail": str(exc.detail),
                "request_id": getattr(request.state, "request_id", ""),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exc_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "validation_error",
                "detail": "Request validation failed",
                "request_id": getattr(request.state, "request_id", ""),
                "fields": [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()],
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exc_handler(request: Request, exc: Exception):  # noqa: ARG001
        logger.exception("unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_error",
                "detail": "An unexpected error occurred.",
                "request_id": getattr(request.state, "request_id", ""),
            },
        )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(studies.router)
    app.include_router(analysis.router)
    app.include_router(reports.router)

    # Create tables eagerly rather than only in the startup hook. The ASGI
    # lifespan event does not fire under every runner — notably a bare
    # TestClient and Vercel's serverless runtime — and a missing table shows up
    # as a 500 on the first request, which is a miserable thing to debug.
    # create_all() is idempotent, so calling it here and on startup is safe.
    init_db()

    @app.on_event("startup")
    def _startup() -> None:
        init_db()
        logger.info(
            "%s started | env=%s | engine=%s v%s",
            settings.app_name,
            settings.environment,
            ENGINE_NAME,
            ENGINE_VERSION,
        )

    @app.get("/api", include_in_schema=False)
    def api_root() -> dict:
        return {
            "app": settings.app_name,
            "engine": ENGINE_NAME,
            "version": ENGINE_VERSION,
            "docs": "/api/docs",
            "disclaimer": DISCLAIMER,
        }

    if os.path.isdir(STATIC_DIR):
        app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    return app


app = create_app()
