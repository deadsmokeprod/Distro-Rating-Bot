from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from bot.config import load_config


config = load_config()
DATABASE_URL = f"sqlite+aiosqlite:///{config.db_path}"

engine: AsyncEngine = create_async_engine(
    DATABASE_URL, echo=False, future=True
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
