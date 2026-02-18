from __future__ import annotations

import time
from collections import defaultdict, deque

_WINDOWS: dict[str, deque[float]] = defaultdict(deque)


def is_rate_limited(key: str, limit: int, window_sec: int) -> bool:
    """Return True when key exceeded allowed attempts in time window."""
    now = time.monotonic()
    window = _WINDOWS[key]
    while window and (now - window[0]) > window_sec:
        window.popleft()
    if len(window) >= limit:
        return True
    window.append(now)
    return False
