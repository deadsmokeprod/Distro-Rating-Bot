from sqlalchemy.ext.asyncio import AsyncEngine
from .models import Base


async def run_migrations(engine: AsyncEngine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
