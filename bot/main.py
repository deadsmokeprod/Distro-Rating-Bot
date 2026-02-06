from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.exc import SQLAlchemyError

from .config import Config
from .db import Base, create_engine, create_sessionmaker
from .handlers import menu_router, start_router
from .logging_config import setup_logging
from .middlewares.db import DbSessionMiddleware
from .middlewares.error_handler import ErrorMiddleware
from .services.erp_sync import sync_sales

logger = logging.getLogger(__name__)


def _ensure_dirs(db_path: str) -> None:
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        os.makedirs("logs", exist_ok=True)
    except OSError as exc:
        print(f"DB_PATH directory is not accessible: {exc}")
        sys.exit(1)


async def _init_db(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _create_scheduler(config: Config, sessionmaker) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    try:
        trigger = CronTrigger.from_crontab(config.sync_cron)
    except ValueError:
        logger.warning("Invalid SYNC_CRON, fallback to every 30 minutes")
        trigger = CronTrigger.from_crontab("*/30 * * * *")

    async def scheduled_sync():
        async with sessionmaker() as session:
            try:
                await sync_sales(session, config.erp_url, config.erp_username, config.erp_password)
            except Exception:
                logger.exception("Scheduled ERP sync failed")

    scheduler.add_job(scheduled_sync, trigger=trigger)
    return scheduler


async def main() -> None:
    setup_logging()
    config = Config.load()
    _ensure_dirs(config.db_path)

    engine = create_engine(config.db_path)
    sessionmaker = create_sessionmaker(engine)

    try:
        await _init_db(engine)
    except SQLAlchemyError:
        logger.exception("Failed to initialize database")
        sys.exit(1)

    bot = Bot(token=config.bot_token)
    dp = Dispatcher()
    dp["config"] = config

    dp.update.outer_middleware(ErrorMiddleware())
    dp.update.outer_middleware(DbSessionMiddleware(sessionmaker))

    dp.include_router(start_router)
    dp.include_router(menu_router)

    scheduler = _create_scheduler(config, sessionmaker)
    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
