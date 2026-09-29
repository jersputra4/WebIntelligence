"""FastAPI entrypoint for the Specter Intel social media intelligence dashboard."""
from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import history, search, system
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.services.ensembledata import build_provider
from app.services.history import HistoryRepository
from app.services.rate_limiter import SlidingWindowRateLimiter
from app.services.search_service import SearchService
from app.utils.logger import get_logger, setup_logging

log = get_logger("app")

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; "
    "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


def create_app(settings: Settings | None = None,
               transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, secrets=[settings.ensembledata_api_key])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository = HistoryRepository(settings.database_path)
        provider = build_provider(settings, transport=transport)
        app.state.settings = settings
        app.state.repository = repository
        app.state.provider = provider
        app.state.rate_limiter = SlidingWindowRateLimiter(
            settings.rate_limit_requests, settings.rate_limit_window_seconds
        )
        app.state.search_service = SearchService(provider, repository, settings.provider_mode)
        app.state.avatar_client = httpx.AsyncClient(timeout=8.0, follow_redirects=False)
        log.info("Started (env=%s, provider mode=%s, api key configured=%s)",
                 settings.app_env, settings.provider_mode, settings.api_key_configured)
        try:
            yield
        finally:
            await provider.aclose()
            await app.state.avatar_client.aclose()
            repository.close()

    app = FastAPI(
        title="Specter Intel — Social Media Intelligence API",
        version="1.0.0",
        description="Username lookup backed by EnsembleData. The API key never leaves the server.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if not request.url.path.startswith(("/docs", "/redoc")):
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if request.url.path.startswith("/api/") and request.url.path != "/api/avatar":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return JSONResponse(exc.to_dict(), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        fields = sorted({str(err.get("loc", ["", "?"])[-1]) for err in exc.errors()})
        return JSONResponse(
            {"success": False, "error": {"code": "INVALID_REQUEST",
                                          "message": f"Invalid request parameter: {', '.join(fields)}"}},
            status_code=400,
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception):
        log.exception("Unhandled error", exc_info=exc)
        return JSONResponse(AppError().to_dict(), status_code=500)

    app.include_router(system.router)
    app.include_router(search.router)
    app.include_router(history.router)

    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app


app = create_app()
