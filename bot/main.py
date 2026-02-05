import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from bot.config import load_config
from bot.db.migrations import init_db
from bot.middlewares.access import AccessMiddleware
from bot.middlewares.auth import AuthMiddleware
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.menu_logger import MenuLoggerMiddleware
from bot.middlewares.support_lock import SupportLockMiddleware
from bot.routers import profile, rating, sales_confirm, settings, start, support
from bot.services.erp_sync import sync_from_erp
from bot.db.engine import SessionLocal


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("logs/app.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


async def schedule_sync(scheduler: AsyncIOScheduler, config) -> None:
    async def job():
        async with SessionLocal() as session:
            await sync_from_erp(session, config.timezone)

    trigger = CronTrigger.from_crontab(config.sync_cron, timezone=config.timezone)
    scheduler.add_job(job, trigger)


async def main() -> None:
    load_dotenv()
    config = load_config()
    setup_logging()
    await init_db()

    bot = Bot(token=config.bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.middleware(DbSessionMiddleware())
    dp.message.middleware(AuthMiddleware())
    dp.message.middleware(AccessMiddleware())
    dp.message.middleware(SupportLockMiddleware())
    dp.message.middleware(MenuLoggerMiddleware())

    dp.include_router(start.router)
    dp.include_router(settings.router)
    dp.include_router(rating.router)
    dp.include_router(sales_confirm.router)
    dp.include_router(profile.router)
    dp.include_router(support.router)

    scheduler = AsyncIOScheduler()
    await schedule_sync(scheduler, config)
    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
