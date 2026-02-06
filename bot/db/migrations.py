from sqlalchemy.ext.asyncio import AsyncEngine

from bot.db.models import Base


async def run_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
