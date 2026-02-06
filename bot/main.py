import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import Config
from bot.db.engine import create_engine, create_session_factory
from bot.db.migrations import run_migrations
from bot.middlewares.auth import AuthMiddleware
from bot.middlewares.support_lock import SupportLockMiddleware
from bot.routers import profile, rating, sales_confirm, settings, start, support
from bot.services.sync_service import sync_erp


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


async def main() -> None:
    setup_logging()
    config = Config.load()
    if not config.bot_token:
        raise SystemExit("BOT_TOKEN is required")

    db_path = Path(config.db_path)
    if db_path.parent and not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(config.db_path)
    session_factory = create_session_factory(engine)
    await run_migrations(engine)

    bot = Bot(token=config.bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    dp.workflow_data.update(config=config, session_factory=session_factory)

    dp.message.middleware(AuthMiddleware(session_factory))
    dp.message.middleware(SupportLockMiddleware(session_factory))

    dp.include_router(start.router)
    dp.include_router(rating.router)
    dp.include_router(sales_confirm.router)
    dp.include_router(profile.router)
    dp.include_router(settings.router)
    dp.include_router(support.router)

    scheduler = AsyncIOScheduler(timezone=config.timezone)
    scheduler.add_job(sync_erp, CronTrigger.from_crontab(config.sync_cron), args=[config, session_factory])
    scheduler.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
