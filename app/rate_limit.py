"""Tiny in-memory rate limiter used by the public chat endpoint.

Single-process scope. Good enough while the chatbot runs on one
EasyPanel replica. If we ever scale horizontally, swap this for a
Redis-backed limiter (the Redis option `slowapi[redis]` plugs in
without touching call-sites).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

# bucket key -> deque of recent timestamps (monotonic seconds)
_BUCKETS: defaultdict[str, deque[float]] = defaultdict(deque)


def hit(key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    """Register a hit and tell the caller if it's allowed.

    Returns (allowed, retry_after_seconds). `retry_after_seconds`
    is 0 when allowed. Mutates the bucket in place to keep memory
    bounded.
    """
    if limit <= 0 or window_seconds <= 0:
        return True, 0
    now = time.monotonic()
    bucket = _BUCKETS[key]
    while bucket and now - bucket[0] >= window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        oldest = bucket[0]
        retry_after = max(1, int(window_seconds - (now - oldest)))
        return False, retry_after
    bucket.append(now)
    return True, 0


def client_ip(request) -> str:  # type: ignore[no-untyped-def]
    """Best-effort caller IP. Honours X-Forwarded-For and X-Real-IP first
    so the limiter works correctly behind nginx/Caddy/EasyPanel."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"
