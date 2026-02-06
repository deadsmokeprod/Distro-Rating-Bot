from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Config
from .db import Database
from .handlers.main import router
from .services.erp import sync_erp_sales


def setup_logging() -> None:
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler = RotatingFileHandler("logs/bot.log", maxBytes=5_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler(sys.stdout)])


async def on_error(event: ErrorEvent) -> None:
    logging.exception("Unhandled exception", exc_info=event.exception)
    if event.update and event.update.message:
        try:
            await event.update.message.answer(
                "⚠️ Ошибка. Попробуйте ещё раз. Если повторяется — напишите в поддержку."
            )
        except Exception:
            logging.exception("Failed to send error message")


async def schedule_sync(scheduler: AsyncIOScheduler, db: Database, config: Config) -> None:
    def _get_trigger() -> CronTrigger:
        try:
            return CronTrigger.from_crontab(config.sync_cron)
        except Exception:
            logging.warning("Invalid SYNC_CRON, falling back to every 30 minutes")
            return CronTrigger.from_crontab("*/30 * * * *")

    async def _job() -> None:
        async with db.session()() as session:
            await sync_erp_sales(session, config.erp_url, config.erp_username, config.erp_password)
            await session.commit()

    scheduler.add_job(_job, _get_trigger())


async def main() -> None:
    config = Config.load()
    setup_logging()

    bot = Bot(token=config.bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    dp.include_router(router)
    dp.errors.register(on_error)

    db = Database(config.db_path)
    await db.init_models()

    bot["config"] = config
    bot["db"] = db

    scheduler = AsyncIOScheduler(timezone=config.timezone)
    await schedule_sync(scheduler, db, config)
    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
