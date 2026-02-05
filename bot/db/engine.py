from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


_engine = None
_sessionmaker = None


def init_engine(db_path: str):
    global _engine, _sessionmaker
    db_url = f"sqlite+aiosqlite:///{db_path}"
    _engine = create_async_engine(db_url, echo=False, future=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)



def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Database engine not initialized")
    return _sessionmaker


def get_engine():
    if _engine is None:
        raise RuntimeError("Database engine not initialized")
    return _engine


async def dispose_engine():
    if _engine is not None:
        await _engine.dispose()
