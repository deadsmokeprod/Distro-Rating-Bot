from __future__ import annotations

from bot.db.engine import create_engine
from bot.db.models import Base


async def init_db() -> None:
    engine = create_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
