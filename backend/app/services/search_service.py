"""Search orchestration: provider calls, normalization results, history logging."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from app.core.errors import AppError
from app.schemas.search import AccountResult, Platform, ProviderIssue, SearchMeta, SearchResponse
from app.services.ensembledata import SUPPORTED_PLATFORMS
from app.services.history import HistoryRepository
from app.utils.logger import get_logger

log = get_logger("search")


class SearchService:
    def __init__(self, provider, repository: HistoryRepository, mode: str):
        self._provider = provider
        self._repo = repository
        self._mode = mode

    async def search(self, username: str, platform: Platform) -> SearchResponse:
        platforms = list(SUPPORTED_PLATFORMS) if platform == Platform.all else [platform.value]
        started = time.perf_counter()
        outcomes = await asyncio.gather(
            *(self._provider.fetch_account(p, username) for p in platforms), return_exceptions=True
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        results: list[AccountResult] = []
        errors: list[tuple[str, AppError]] = []
        for name, outcome in zip(platforms, outcomes):
            if isinstance(outcome, AppError):
                errors.append((name, outcome))
            elif isinstance(outcome, BaseException):
                log.exception("Unexpected provider failure for %s", name, exc_info=outcome)
                errors.append((name, AppError()))
            elif outcome is not None:
                results.append(outcome)

        # Fail the whole request only if nothing succeeded and at least one call errored.
        if errors and len(errors) == len(platforms):
            _, error = errors[0]
            self._log(username, platform.value, "error", error.status_code, [], latency_ms, error.code)
            raise error

        status = "success" if results else "not_found"
        self._log(username, platform.value, status, 200, results, latency_ms, None)
        log.info("search username=%s platform=%s results=%d latency=%dms",
                 username, platform.value, len(results), latency_ms)
        return SearchResponse(
            query=username,
            platform=platform,
            results=results,
            warnings=[ProviderIssue(platform=name, code=err.code, message=err.message) for name, err in errors],
            meta=SearchMeta(
                provider="EnsembleData",
                mode=self._mode,
                latency_ms=latency_ms,
                searched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )

    def _log(self, username, platform, status, status_code, results, latency_ms, error_code):
        try:
            self._repo.record_search(username=username, platform=platform, status=status,
                                     status_code=status_code, results=results,
                                     latency_ms=latency_ms, error_code=error_code)
        except Exception:  # history must never break a search
            log.exception("Failed to record search history")
