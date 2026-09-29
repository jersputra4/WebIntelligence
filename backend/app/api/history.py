"""Search history endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.schemas.search import HistoryItem, HistoryResponse

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", response_model=HistoryResponse)
async def list_history(request: Request, limit: int = Query(20, ge=1, le=200),
                       offset: int = Query(0, ge=0)) -> HistoryResponse:
    total, items = request.app.state.repository.list_history(limit, offset)
    return HistoryResponse(total=total, items=[HistoryItem(**item) for item in items])


@router.delete("")
async def clear_history(request: Request) -> dict:
    deleted = request.app.state.repository.clear_history()
    return {"success": True, "deleted": deleted}
