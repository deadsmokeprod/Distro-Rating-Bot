from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.config import Config
from bot.db import create_engine, create_sessionmaker, init_db
from bot.handlers import back, menu, profile, rating, sales, settings, start, support, support_relay
from bot.logging import setup_logging
from bot.middlewares.config import ConfigMiddleware
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.error import ErrorMiddleware
from bot.scheduler import setup_scheduler

logger = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()
    config = Config.load()

    engine = create_engine(config.db_path)
    await init_db(engine)
    sessionmaker = create_sessionmaker(engine)

    bot = Bot(token=config.bot_token)

    dp = Dispatcher()
    dp.update.middleware(ErrorMiddleware())
    dp.update.middleware(ConfigMiddleware(config))
    dp.update.middleware(DbSessionMiddleware(sessionmaker))

    dp.include_router(start.router)
    dp.include_router(menu.router)
    dp.include_router(rating.router)
    dp.include_router(profile.router)
    dp.include_router(sales.router)
    dp.include_router(settings.router)
    dp.include_router(support.router)
    dp.include_router(back.router)
    dp.include_router(support_relay.router)

    scheduler = setup_scheduler(
        sessionmaker,
        config.erp_url,
        config.erp_username,
        config.erp_password,
        config.sync_cron,
    )
    scheduler.start()

    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
