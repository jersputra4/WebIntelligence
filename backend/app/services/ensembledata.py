"""EnsembleData API client.

EnsembleData authenticates with a ``token`` query parameter. The token only
ever lives in this module (server side); it is never returned to the browser
and is redacted from logs.

Endpoints used (verify against your EnsembleData plan/documentation):
    Twitter/X  : GET /twitter/user/info?name=<username>
    TikTok     : GET /tt/user/info?username=<username>
    Instagram  : GET /instagram/user/info?username=<username>
    Quota usage: GET /customer/get-used-units?date=YYYY-MM-DD
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import (
    AppError,
    ProviderError,
    ProviderMalformedResponse,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnauthorized,
    ProviderUnavailable,
)
from app.schemas.search import AccountResult
from app.services.normalizer import normalize
from app.utils.logger import get_logger

log = get_logger("ensembledata")

PLATFORM_ENDPOINTS: dict[str, tuple[str, str]] = {
    # platform: (path, username query parameter name)
    "twitter": ("/twitter/user/info", "name"),
    "tiktok": ("/tt/user/info", "username"),
    "instagram": ("/instagram/user/info", "username"),
}
SUPPORTED_PLATFORMS = tuple(PLATFORM_ENDPOINTS)

NOT_FOUND_HINTS = ("not found", "not exist", "doesn't exist", "no user", "user_not_found", "notfound")


@dataclass
class ProviderStatus:
    last_ok: bool | None = None
    last_latency_ms: int | None = None
    last_checked: float | None = None
    last_error_code: str | None = None


class EnsembleDataClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.ensembledata_base_url,
            timeout=httpx.Timeout(settings.request_timeout),
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "SpecterIntel/1.0"},
        )
        self.status = ProviderStatus()
        self._quota_cache: tuple[float, int | None] | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ public
    async def fetch_account(self, platform: str, username: str) -> AccountResult | None:
        """Return a normalized account, ``None`` if not found, or raise an AppError."""
        path, param = PLATFORM_ENDPOINTS[platform]
        payload = await self._request(path, {param: username})
        if payload is None:
            return None
        return normalize(platform, payload, username)

    async def used_units_today(self) -> int | None:
        """Units consumed today according to EnsembleData (cached for 60 s)."""
        now = time.monotonic()
        if self._quota_cache and now - self._quota_cache[0] < 60:
            return self._quota_cache[1]
        used: int | None = None
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            payload = await self._request("/customer/get-used-units", {"date": today}, track=False)
            value = payload.get("data") if isinstance(payload, dict) else payload
            if isinstance(value, dict):
                value = value.get("units", value.get("used_units"))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                used = int(value)
        except AppError as exc:
            log.info("Quota lookup failed: %s", exc.code)
        self._quota_cache = (now, used)
        return used

    # ----------------------------------------------------------------- private
    def _build_params(self, params: dict[str, str]) -> dict[str, str]:
        if not self._settings.api_key_configured:
            raise ProviderNotConfigured(
                "EnsembleData API key is not configured on the server (ENSEMBLEDATA_API_KEY)"
            )
        return {**params, "token": self._settings.ensembledata_api_key}

    async def _request(self, path: str, params: dict[str, str], *, track: bool = True) -> Any:
        query = self._build_params(params)
        attempts = 1 + self._settings.request_retries
        last_error: AppError | None = None
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                response = await self._client.get(path, params=query)
                result = self._handle_response(response)
                if track:
                    self._record(True, started)
                return result
            except httpx.TimeoutException:
                last_error = ProviderTimeout()
            except httpx.TransportError:
                last_error = ProviderUnavailable()
            except ProviderUnavailable as exc:  # 5xx -> retryable
                last_error = exc
            except AppError as exc:  # non-retryable provider error
                if track:
                    self._record(False, started, exc.code)
                raise
            log.warning("EnsembleData %s attempt %d/%d failed: %s", path, attempt, attempts, last_error.code)
            if track:
                self._record(False, started, last_error.code)
            if attempt < attempts:
                await asyncio.sleep(0.5 * attempt)
        assert last_error is not None
        raise last_error

    def _record(self, ok: bool, started: float, code: str | None = None) -> None:
        self.status.last_ok = ok
        self.status.last_latency_ms = int((time.perf_counter() - started) * 1000)
        self.status.last_checked = time.time()
        self.status.last_error_code = code

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:300].lower()
        if isinstance(body, dict):
            return str(body.get("detail") or body.get("message") or body.get("error") or "").lower()
        return ""

    def _handle_response(self, response: httpx.Response) -> Any:
        status = response.status_code
        if status == 200:
            try:
                return response.json()
            except ValueError as exc:
                raise ProviderMalformedResponse() from exc
        detail = self._detail(response)
        if status == 404 or (status in (400, 422) and any(h in detail for h in NOT_FOUND_HINTS)):
            return None
        if status in (401, 403, 491):
            raise ProviderUnauthorized()
        if status in (429, 495):
            raise ProviderRateLimited()
        if status >= 500:
            raise ProviderUnavailable()
        log.warning("EnsembleData unexpected status %s: %s", status, detail[:120])
        raise ProviderError()


class DemoProvider:
    """Offline provider producing clearly-labelled synthetic data.

    Used when no API key is configured (PROVIDER_MODE=auto) so the dashboard can be
    explored without spending EnsembleData units. Values are deterministic per handle.
    """

    def __init__(self) -> None:
        self.status = ProviderStatus()

    async def aclose(self) -> None:  # parity with EnsembleDataClient
        return None

    async def used_units_today(self) -> int | None:
        return None

    async def fetch_account(self, platform: str, username: str) -> AccountResult | None:
        started = time.perf_counter()
        seed = int(hashlib.sha256(f"{platform}:{username.lower()}".encode()).hexdigest(), 16)
        await asyncio.sleep(0.25 + (seed % 400) / 1000)
        self.status = ProviderStatus(True, int((time.perf_counter() - started) * 1000), time.time())
        lowered = username.lower()
        if lowered.startswith(("notfound", "unknown")):
            return None
        followers = 500 + seed % 5_000_000
        created_year = 2008 + seed % 15
        base = {
            "twitter": f"https://x.com/{username}",
            "tiktok": f"https://www.tiktok.com/@{username}",
            "instagram": f"https://www.instagram.com/{username}/",
        }[platform]
        return AccountResult(
            platform=platform,
            username=username,
            display_name=f"Demo · {username}",
            user_id=str(seed % 10**12),
            profile_url=base,
            avatar=None,
            bio="Synthetic demo profile. Configure ENSEMBLEDATA_API_KEY on the server to retrieve live account data.",
            location="Demo Environment",
            verified=seed % 3 == 0,
            private=False,
            followers=followers,
            following=50 + (seed >> 8) % 2_000,
            posts=10 + (seed >> 16) % 20_000,
            likes=(seed >> 24) % 1_000_000 if platform != "instagram" else None,
            created_at=datetime(created_year, 1 + seed % 12, 1 + seed % 28, tzinfo=timezone.utc).isoformat(),
            source="demo",
        )


def build_provider(settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
    if settings.provider_mode == "mock":
        return DemoProvider()
    return EnsembleDataClient(settings, transport=transport)
