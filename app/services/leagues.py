from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

from app.services.ratings import RatingRow


LEAGUES = [
    "Bronze",
    "Silver",
    "Gold",
    "Sapphire",
    "Ruby",
    "Emerald",
    "Amethyst",
    "Pearl",
    "Obsidian",
    "Diamond",
]


@dataclass(frozen=True)
class LeagueInfo:
    name: str
    to_next_volume: float | None


def compute_league(rows: List[RatingRow], tg_user_id: int) -> LeagueInfo:
    if not rows:
        return LeagueInfo(name="Bronze", to_next_volume=None)
    total = len(rows)
    current = next((r for r in rows if r.tg_user_id == tg_user_id), None)
    if not current:
        return LeagueInfo(name="Bronze", to_next_volume=None)
    percent = (current.global_rank - 1) / total
    idx = len(LEAGUES) - 1 - int(percent * len(LEAGUES))
    idx = max(0, min(idx, len(LEAGUES) - 1))
    name = LEAGUES[idx]

    if idx == len(LEAGUES) - 1:
        return LeagueInfo(name=name, to_next_volume=None)

    # next higher league (idx+1) boundary
    higher_idx = idx + 1
    top_count = math.ceil(total * (len(LEAGUES) - higher_idx) / len(LEAGUES))
    top_count = max(1, min(top_count, total))
    threshold_rank = top_count
    threshold_row = next((r for r in rows if r.global_rank == threshold_rank), None)
    if not threshold_row:
        return LeagueInfo(name=name, to_next_volume=None)
    to_next = max(0.0, threshold_row.total_volume - current.total_volume)
    return LeagueInfo(name=name, to_next_volume=to_next)
