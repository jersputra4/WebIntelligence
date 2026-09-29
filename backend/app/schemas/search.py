"""Pydantic schemas for the public API."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Platform(str, Enum):
    twitter = "twitter"
    instagram = "instagram"
    tiktok = "tiktok"
    all = "all"


class AccountResult(BaseModel):
    """Provider-agnostic, normalized account record."""

    platform: str
    username: str
    display_name: Optional[str] = None
    user_id: Optional[str] = None
    profile_url: Optional[str] = None
    avatar: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    external_url: Optional[str] = None
    verified: bool = False
    private: Optional[bool] = None
    followers: Optional[int] = None
    following: Optional[int] = None
    posts: Optional[int] = None
    likes: Optional[int] = None
    created_at: Optional[str] = None
    source: str = Field("ensembledata", description="'ensembledata' or 'demo'")


class ProviderIssue(BaseModel):
    platform: str
    code: str
    message: str


class SearchMeta(BaseModel):
    provider: str
    mode: str
    latency_ms: int
    searched_at: str


class SearchResponse(BaseModel):
    success: bool = True
    query: str
    platform: Platform
    results: list[AccountResult]
    warnings: list[ProviderIssue] = []
    meta: SearchMeta


class TrendPoint(BaseModel):
    captured_at: str
    followers: Optional[int] = None
    following: Optional[int] = None
    posts: Optional[int] = None


class TrendResponse(BaseModel):
    success: bool = True
    platform: str
    username: str
    points: list[TrendPoint]


class HistoryItem(BaseModel):
    id: int
    username: str
    platform: str
    searched_at: str
    result_count: int
    status: str
    status_code: int
    latency_ms: Optional[int] = None
    error_code: Optional[str] = None
    display_name: Optional[str] = None
    avatar: Optional[str] = None
    verified: bool = False
    result_platform: Optional[str] = None


class HistoryResponse(BaseModel):
    success: bool = True
    total: int
    items: list[HistoryItem]
