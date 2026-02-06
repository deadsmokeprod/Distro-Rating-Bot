from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


def create_engine(db_path: str):
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}")


def create_session_factory(engine) -> sessionmaker:
    return sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
