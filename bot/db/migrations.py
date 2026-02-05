from pathlib import Path

from bot.config import load_config
from bot.db.engine import engine
from bot.db.models import Base


async def init_db() -> None:
    config = load_config()
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
