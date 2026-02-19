from __future__ import annotations

import time
from collections import defaultdict, deque

_WINDOWS: dict[str, deque[float]] = defaultdict(deque)


def _drop_expired(window: deque[float], now: float, window_sec: int) -> None:
    while window and (now - window[0]) > window_sec:
        window.popleft()


def is_rate_limited(key: str, limit: int, window_sec: int) -> bool:
    """Return True when key exceeded allowed attempts in time window."""
    token = acquire_rate_limit(key, limit=limit, window_sec=window_sec)
    return token is None


def acquire_rate_limit(key: str, limit: int, window_sec: int) -> float | None:
    """Reserve one attempt slot; return token when acquired, otherwise None."""
    now = time.monotonic()
    window = _WINDOWS[key]
    _drop_expired(window, now=now, window_sec=window_sec)
    if len(window) >= limit:
        return None
    window.append(now)
    return now


def release_rate_limit(key: str, token: float) -> None:
    """Release previously reserved slot token (best-effort)."""
    window = _WINDOWS.get(key)
    if not window:
        return
    for idx in range(len(window) - 1, -1, -1):
        if window[idx] == token:
            del window[idx]
            break
