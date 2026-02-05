from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import load_config
from bot.db.engine import create_engine, get_sessionmaker
from bot.db.migrations import init_db
from bot.middlewares.auth import AuthMiddleware
from bot.middlewares.menu_access import MenuAccessMiddleware
from bot.middlewares.registered_guard import RegisteredGuardMiddleware
from bot.middlewares.support_lock import SupportLockMiddleware
from bot.routers.profile import router as profile_router
from bot.routers.rating import router as rating_router
from bot.routers.sales_confirm import router as sales_router
from bot.routers.settings import router as settings_router
from bot.routers.start import router as start_router
from bot.routers.support import router as support_router
from bot.services.erp_sync import sync_erp
from bot.services.time_utils import get_last_closed_month


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    handler = RotatingFileHandler("logs/app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler, logging.StreamHandler()],
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def scheduled_sync() -> None:
    config = load_config()
    month_key, start, end = get_last_closed_month(config.timezone)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await sync_erp(session, start, end, month_key)


async def main() -> None:
    setup_logging()
    config = load_config()
    create_engine()
    await init_db()

    bot = Bot(token=config.bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher()

    dp.message.middleware(AuthMiddleware())
    dp.message.middleware(RegisteredGuardMiddleware())
    dp.message.middleware(MenuAccessMiddleware())
    dp.message.middleware(SupportLockMiddleware())

    dp.include_router(start_router)
    dp.include_router(rating_router)
    dp.include_router(sales_router)
    dp.include_router(profile_router)
    dp.include_router(settings_router)
    dp.include_router(support_router)

    scheduler = AsyncIOScheduler()
    cron_parts = config.sync_cron.split()
    if len(cron_parts) == 5:
        minute, hour, day, month, day_of_week = cron_parts
        scheduler.add_job(
            scheduled_sync,
            "cron",
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=config.timezone,
        )
    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
