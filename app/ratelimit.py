"""A small, dependency-free sliding-window rate limiter.

Implemented in-process rather than pulled from a library so the behaviour is
explicit and unit-testable. For a multi-instance deployment, back this with
Redis — the interface (`check`) is the only thing callers depend on.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Limit:
    """A limit expressed as `count` requests per `window_seconds`."""

    count: int
    window_seconds: float

    @classmethod
    def parse(cls, spec: str) -> Limit:
        """Parse '10/minute', '20/second', '120/hour'."""
        try:
            amount_str, unit = spec.split("/", 1)
            amount = int(amount_str.strip())
        except (ValueError, AttributeError):
            return cls(count=60, window_seconds=60.0)
        unit = unit.strip().lower()
        windows = {
            "second": 1.0,
            "sec": 1.0,
            "minute": 60.0,
            "min": 60.0,
            "hour": 3600.0,
            "hr": 3600.0,
        }
        return cls(count=max(1, amount), window_seconds=windows.get(unit, 60.0))


class RateLimiter:
    """Sliding-window limiter keyed by an arbitrary string (usually client IP)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: Limit, now: float | None = None) -> tuple[bool, float]:
        """Record a hit. Returns (allowed, retry_after_seconds).

        `retry_after_seconds` is 0.0 when allowed.
        """
        now = time.monotonic() if now is None else now
        cutoff = now - limit.window_seconds
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit.count:
                retry_after = max(0.0, bucket[0] + limit.window_seconds - now)
                return False, retry_after
            bucket.append(now)
            return True, 0.0

    def reset(self, key: str | None = None) -> None:
        """Clear one key, or everything when key is None. Used by tests."""
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)
