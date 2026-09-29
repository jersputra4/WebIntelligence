"""Account search and trend endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import client_ip
from app.core.errors import RateLimited, ValidationFailed
from app.schemas.search import Platform, SearchResponse, TrendPoint, TrendResponse
from app.utils.validation import normalize_username

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search", response_model=SearchResponse)
async def search_account(
    request: Request,
    response: Response,
    username: str | None = Query(None, max_length=64, description="Account handle, with or without '@'"),
    platform: Platform = Query(Platform.twitter, description="twitter | instagram | tiktok | all"),
) -> SearchResponse:
    state = request.app.state.rate_limiter.hit(client_ip(request))
    response.headers["X-RateLimit-Limit"] = str(state.limit)
    response.headers["X-RateLimit-Remaining"] = str(state.remaining)
    if not state.allowed:
        raise RateLimited(retry_after=state.reset_in or 1)
    clean = normalize_username(username)
    return await request.app.state.search_service.search(clean, platform)


@router.get("/accounts/{platform}/{username}/trend", response_model=TrendResponse)
async def account_trend(request: Request, platform: str, username: str,
                        days: int = Query(30, ge=1, le=365)) -> TrendResponse:
    if platform not in {"twitter", "instagram", "tiktok"}:
        raise ValidationFailed("Unsupported platform", code="INVALID_PLATFORM")
    clean = normalize_username(username)
    points = request.app.state.repository.trend(platform, clean, days)
    return TrendResponse(platform=platform, username=clean, points=[TrendPoint(**p) for p in points])
