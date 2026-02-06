from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

from app.config import load_config
from app.db.sqlite import init_db
from app.handlers import manager, seller, start


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

    dp.include_router(start.router)
    dp.include_router(manager.router)
    dp.include_router(seller.router)

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logging.getLogger(__name__).info("Bot polling stopped.")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
