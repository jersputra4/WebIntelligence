"""In-memory sliding-window rate limiter (per client key).

Suitable for a single-process MVP. For multi-instance deployments replace it
with a shared store (e.g. Redis) behind the same interface.
"""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class RateLimitState:
    limit: int
    used: int
    remaining: int
    reset_in: int
    allowed: bool


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def _state(self, hits: deque[float], now: float, allowed: bool) -> RateLimitState:
        reset_in = math.ceil(hits[0] + self.window - now) if hits else 0
        return RateLimitState(self.limit, len(hits), max(0, self.limit - len(hits)), max(0, reset_in), allowed)

    def hit(self, key: str) -> RateLimitState:
        """Register a request; ``allowed`` is False when the limit is exceeded."""
        now = self._clock()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) >= self.limit:
                return self._state(hits, now, False)
            hits.append(now)
            return self._state(hits, now, True)

    def peek(self, key: str) -> RateLimitState:
        now = self._clock()
        with self._lock:
            hits = self._prune(key, now)
            state = self._state(hits, now, len(hits) < self.limit)
            if not hits:
                self._hits.pop(key, None)
            return state
