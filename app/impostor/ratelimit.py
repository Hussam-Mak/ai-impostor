"""Tiny in-memory sliding-window rate limiter (single app process)."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

MAX_TRACKED_KEYS = 20_000


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            if len(self._hits) > MAX_TRACKED_KEYS:
                self._prune(now)
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True

    def _prune(self, now: float) -> None:
        stale = [k for k, h in self._hits.items() if not h or now - h[-1] > self._window]
        for key in stale:
            del self._hits[key]
