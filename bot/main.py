import asyncio
import logging
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from .config import load_config
from .db.engine import init_engine, get_sessionmaker, get_engine
from .db.migrations import run_migrations
from .middlewares.db_session import DBSessionMiddleware
from .middlewares.auth import AuthMiddleware
from .middlewares.registration_guard import RegistrationGuardMiddleware
from .middlewares.support_lock import SupportLockMiddleware
from .routers import start, rating, sales_confirm, profile, settings, support
from .services.time_utils import get_last_closed_month, month_range
from .services.erp_client import ErpClient
from .db.repo import upsert_erp_sales


async def sync_erp(config):
    sessionmaker = get_sessionmaker()
    last_closed = get_last_closed_month(config.timezone)
    start_date, end_date = month_range(last_closed)
    client = ErpClient(config.erp_http_url, config.erp_http_user, config.erp_http_password, config.erp_timeout_sec)
    rows = await client.fetch_sales(start_date, end_date)
    async with sessionmaker() as session:
        await upsert_erp_sales(session, rows)


async def main():
    config = load_config()
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(config.logs_path / "app.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    init_engine(config.db_path)
    engine = get_engine()
    await run_migrations(engine)

    bot = Bot(token=config.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    sessionmaker = get_sessionmaker()
    dp.message.middleware(DBSessionMiddleware(sessionmaker))
    dp.message.middleware(AuthMiddleware())
    dp.message.middleware(RegistrationGuardMiddleware())
    dp.message.middleware(SupportLockMiddleware())

    dp.include_router(start.router)
    dp.include_router(rating.router)
    dp.include_router(sales_confirm.router)
    dp.include_router(profile.router)
    dp.include_router(settings.router)
    dp.include_router(support.router)

    dp["config"] = config

    scheduler = AsyncIOScheduler(timezone=config.timezone)
    scheduler.add_job(sync_erp, CronTrigger.from_crontab(config.sync_cron), args=[config])
    scheduler.start()

    await dp.start_polling(bot, config=config)


if __name__ == "__main__":
    asyncio.run(main())
