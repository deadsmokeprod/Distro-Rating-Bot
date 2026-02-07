"""Проверка работоспособности бота: конфиг, БД, токен Telegram."""
from __future__ import annotations

import asyncio
import sys

from aiogram import Bot

from app.config import load_config
from app.db.sqlite import init_db


async def main() -> int:
    print("1. Загрузка конфига...")
    try:
        config = load_config()
        print(f"   OK: BOT_TOKEN=***{config.bot_token[-6:]}, MANAGER_IDS={config.manager_ids}, SUPPORT={config.support_user_id}")
    except Exception as e:
        print(f"   ОШИБКА: {e}")
        return 1

    print("2. Инициализация БД...")
    try:
        await init_db(config.db_path)
        print("   OK")
    except Exception as e:
        print(f"   ОШИБКА: {e}")
        return 1

    print("3. Проверка токена (getMe)...")
    bot = Bot(token=config.bot_token)
    try:
        me = await bot.get_me()
        print(f"   OK: @{me.username} (id={me.id})")
    except Exception as e:
        print(f"   ОШИБКА: {e}")
        return 1
    finally:
        await bot.session.close()

    print("\nВсё в порядке, бот готов к запуску (python bot.py).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
