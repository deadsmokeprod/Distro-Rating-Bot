from __future__ import annotations

import asyncio
from collections import defaultdict

_lock = asyncio.Lock()
_history: dict[int, list[str]] = defaultdict(list)
_MAX_HISTORY_SIZE = 50


async def clear_history(tg_user_id: int) -> None:
    async with _lock:
        _history.pop(int(tg_user_id), None)


async def push_history(tg_user_id: int, screen: str) -> None:
    user_id = int(tg_user_id)
    async with _lock:
        stack = _history[user_id]
        if stack and stack[-1] == screen:
            return
        stack.append(screen)
        if len(stack) > _MAX_HISTORY_SIZE:
            del stack[:-_MAX_HISTORY_SIZE]


async def pop_history(tg_user_id: int) -> str | None:
    user_id = int(tg_user_id)
    async with _lock:
        stack = _history.get(user_id)
        if not stack:
            return None
        return stack.pop()
