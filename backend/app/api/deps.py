"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import Request

from app.core.config import Settings


def client_ip(request: Request) -> str:
    settings: Settings = request.app.state.settings
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
