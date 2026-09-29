"""Health, system status and avatar proxy endpoints."""
from __future__ import annotations

from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Query, Request, Response

from app.api.deps import client_ip
from app.core.errors import AppError, ValidationFailed

router = APIRouter(tags=["system"])

# Profile-image CDNs used by the supported platforms. Only these hosts can be proxied.
AVATAR_HOST_SUFFIXES = (
    "twimg.com",
    "cdninstagram.com",
    "fbcdn.net",
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "tiktokcdn-eu.com",
    "ibyteimg.com",
)
MAX_AVATAR_BYTES = 3 * 1024 * 1024


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/api/system/status")
async def system_status(request: Request) -> dict:
    app_state = request.app.state
    settings = app_state.settings
    provider = app_state.provider
    stats = app_state.repository.daily_stats()
    limit_state = app_state.rate_limiter.peek(client_ip(request))

    quota_remaining = None
    used_units = None
    if settings.provider_mode == "live":
        used_units = await provider.used_units_today()
        if used_units is not None:
            quota_remaining = max(0, settings.ensembledata_daily_units - used_units)

    change_pct = None
    if stats["yesterday"]:
        change_pct = round((stats["today"] - stats["yesterday"]) / stats["yesterday"] * 100, 1)

    status = provider.status
    if settings.provider_mode == "mock":
        provider_state = "demo"
    elif not settings.api_key_configured:
        provider_state = "not_configured"
    elif status.last_ok is False and status.last_error_code in {"PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE"}:
        provider_state = "degraded"
    elif status.last_ok is False and status.last_error_code == "PROVIDER_UNAUTHORIZED":
        provider_state = "unauthorized"
    else:
        provider_state = "online"

    return {
        "success": True,
        "app_env": settings.app_env,
        "provider": {
            "name": "EnsembleData",
            "mode": settings.provider_mode,
            "state": provider_state,
            "api_key_configured": settings.api_key_configured,
            "base_url": settings.ensembledata_base_url,
            "last_latency_ms": status.last_latency_ms,
            "last_error_code": status.last_error_code,
            "timeout_seconds": settings.request_timeout,
            "retries": settings.request_retries,
        },
        "inquiries": {
            "today": stats["today"],
            "today_success": stats["today_success"],
            "yesterday": stats["yesterday"],
            "change_pct": change_pct,
            "total": stats["total"],
            "avg_latency_ms": stats["avg_latency_ms"],
        },
        "quota": {
            "daily_units": settings.ensembledata_daily_units if settings.provider_mode == "live" else None,
            "used_units": used_units,
            "remaining": quota_remaining,
        },
        "rate_limit": {
            "limit": limit_state.limit,
            "used": limit_state.used,
            "remaining": limit_state.remaining,
            "reset_in": limit_state.reset_in,
            "window_seconds": app_state.rate_limiter.window,
        },
    }


def _allowed_avatar_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == s or host.endswith("." + s) for s in AVATAR_HOST_SUFFIXES)


@router.get("/api/avatar")
async def avatar_proxy(request: Request, url: str = Query(..., max_length=2048)) -> Response:
    """Proxy profile images from known platform CDNs (they often block hotlinking)."""
    if not _allowed_avatar_url(url):
        raise ValidationFailed("Avatar host is not allowed", code="AVATAR_HOST_NOT_ALLOWED")
    client: httpx.AsyncClient = request.app.state.avatar_client
    try:
        async with client.stream("GET", url) as upstream:
            content_type = upstream.headers.get("content-type", "")
            if upstream.status_code != 200 or not content_type.startswith("image/"):
                raise AppError("Avatar unavailable", code="AVATAR_UNAVAILABLE", status_code=404)
            body = bytearray()
            async for chunk in upstream.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_AVATAR_BYTES:
                    raise AppError("Avatar too large", code="AVATAR_TOO_LARGE", status_code=413)
    except httpx.HTTPError as exc:
        raise AppError("Avatar unavailable", code="AVATAR_UNAVAILABLE", status_code=404) from exc
    return Response(bytes(body), media_type=content_type.split(";")[0],
                    headers={"Cache-Control": "public, max-age=3600"})
