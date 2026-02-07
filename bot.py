from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import load_config
from app.db import sqlite
from app.db.sqlite import init_db
from app.handlers import manager, seller, start
from app.services.onec_client import OnecClientError
from app.services.turnover_sync import last_30_days_range, moscow_today, sync_turnover
from app.services.ratings import previous_month, write_monthly_snapshot


async def main() -> None:
    config = load_config()

    log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(config.log_path, maxBytes=1_000_000, backupCount=3)
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)

    await init_db(config.db_path)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    scheduler = AsyncIOScheduler(timezone=ZoneInfo("Europe/Moscow"))

    async def scheduled_sync() -> None:
        if not config.onec_url:
            logging.getLogger(__name__).warning("ONEC_URL is not set. Skipping scheduled sync.")
            return
        start, end = last_30_days_range(moscow_today())
        try:
            fetched, upserted = await sync_turnover(config, start, end)
            await sqlite.log_audit(
                config.db_path,
                actor_tg_user_id=None,
                actor_role="system",
                action="SYNC_TURNOVER_AUTO",
                payload={
                    "mode": "last_30_days",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "fetched": fetched,
                    "upserted": upserted,
                },
            )
            logging.getLogger(__name__).info(
                "Scheduled sync done. fetched=%s upserted=%s", fetched, upserted
            )
        except OnecClientError as exc:
            logging.getLogger(__name__).error("Scheduled sync failed: %s", exc)
        except Exception:
            logging.getLogger(__name__).exception("Scheduled sync failed")

    async def scheduled_monthly_snapshot() -> None:
        try:
            target = previous_month(moscow_today())
            await write_monthly_snapshot(config.db_path, target)
            logging.getLogger(__name__).info(
                "Monthly snapshot created for %s", target.strftime("%Y-%m")
            )
        except Exception:
            logging.getLogger(__name__).exception("Monthly snapshot failed")

    scheduler.add_job(
        scheduled_sync,
        CronTrigger(day_of_week="sun", hour=4, minute=0),
        id="turnover_sync",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_monthly_snapshot,
        CronTrigger(day=1, hour=0, minute=10),
        id="monthly_ratings_snapshot",
        replace_existing=True,
    )
    scheduler.start()

    dp.include_router(start.router)
    dp.include_router(manager.router)
    dp.include_router(seller.router)

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logging.getLogger(__name__).info("Bot polling stopped.")
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
