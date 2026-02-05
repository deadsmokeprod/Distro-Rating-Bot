from __future__ import annotations

from typing import Dict, List


def is_allowed(menu_config: Dict[str, List[str]], role: str, button_key: str) -> bool:
    return button_key in menu_config.get(role, [])
