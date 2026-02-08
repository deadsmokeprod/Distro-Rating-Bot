from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
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
from app.services.ratings import current_month_rankings, previous_month, write_monthly_snapshot
from app.services.notifications import can_send_weekly, is_quiet_time, record_notification
from app.services.challenges import ensure_biweekly_challenges


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

    await ensure_biweekly_challenges(config)

    async def scheduled_sync() -> None:
        if not config.onec_url:
            logging.getLogger(__name__).warning("ONEC_URL is not set. Skipping scheduled sync.")
            return
        start, end = last_30_days_range(moscow_today())
        operation_type = config.onec_operation_type
        try:
            fetched, upserted = await sync_turnover(
                config, start, end, operation_type=operation_type
            )
            await sqlite.log_audit(
                config.db_path,
                actor_tg_user_id=None,
                actor_role="system",
                action="SYNC_TURNOVER_AUTO",
                payload={
                    "mode": "last_30_days",
                    "operationType": operation_type,
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

    async def scheduled_reminders() -> None:
        if is_quiet_time(config):
            return
        try:
            rows = await sqlite.fetch_all(
                config.db_path,
                "SELECT tg_user_id, org_id, last_seen_at FROM users WHERE role = 'seller'",
            )
            rankings = await current_month_rankings(config.db_path)
            ranking_map = {r.tg_user_id: r for r in rankings}
            now = datetime.now(ZoneInfo("Europe/Moscow"))

            for row in rows:
                tg_user_id = int(row["tg_user_id"])
                if not await can_send_weekly(config.db_path, tg_user_id):
                    continue
                # skip if fixed sales in last 24h
                recent = await sqlite.fetch_one(
                    config.db_path,
                    """
                    SELECT 1 AS exists_flag
                    FROM sales_claims
                    WHERE claimed_by_tg_user_id = ?
                      AND claimed_at >= ?
                    """,
                    (tg_user_id, (now - timedelta(days=1)).isoformat()),
                )
                if recent:
                    continue

                current = ranking_map.get(tg_user_id)
                if not current:
                    continue

                # rank drop vs previous month
                prev = await sqlite.fetch_one(
                    config.db_path,
                    """
                    SELECT company_rank
                    FROM ratings_monthly
                    WHERE month = ? AND tg_user_id = ?
                    """,
                    (previous_month(moscow_today()).strftime("%Y-%m"), tg_user_id),
                )
                if prev and current.company_rank > int(prev["company_rank"]):
                    text = (
                        f"Вы были #{int(prev['company_rank'])} в компании, сейчас #{current.company_rank}. "
                        "Зафиксируйте продажи, чтобы вернуться."
                    )
                    await bot.send_message(tg_user_id, text)
                    await record_notification(
                        config.db_path,
                        tg_user_id,
                        "rank_drop",
                        "sent",
                        {"prev": int(prev["company_rank"]), "current": current.company_rank},
                    )
                    continue

                # company rival reminder
                org_rows = [r for r in rankings if r.org_id == current.org_id]
                org_rows.sort(key=lambda r: r.company_rank)
                idx = next((i for i, r in enumerate(org_rows) if r.tg_user_id == tg_user_id), None)
                if idx is not None:
                    rival = None
                    if idx > 0:
                        rival = org_rows[idx - 1]
                    elif idx + 1 < len(org_rows):
                        rival = org_rows[idx + 1]
                    if rival:
                        diff = abs(rival.total_volume - current.total_volume)
                        if diff <= max(1.0, current.total_volume * 0.1):
                            text = (
                                f"В компании рядом с вами {rival.full_name}. "
                                f"Разница всего {diff:g}. Зафиксируйте продажи, чтобы обогнать!"
                            )
                            await bot.send_message(tg_user_id, text)
                            await record_notification(
                                config.db_path,
                                tg_user_id,
                                "company_rival",
                                "sent",
                                {"rival_id": rival.tg_user_id, "diff": diff},
                            )
                            continue

                # inactive 3+ days
                last_seen = row["last_seen_at"]
                if last_seen:
                    last_seen_dt = datetime.fromisoformat(last_seen)
                    if (now - last_seen_dt).days >= 3:
                        org = await sqlite.get_org_by_id(config.db_path, int(row["org_id"]))
                        if org:
                            unclaimed = await sqlite.count_unclaimed_turnover(
                                config.db_path, str(org["inn"])
                            )
                            text = (
                                f"У вас есть {unclaimed} незакреплённых продаж. "
                                "Зафиксируйте — это влияет на рейтинг."
                            )
                            await bot.send_message(tg_user_id, text)
                            await record_notification(
                                config.db_path,
                                tg_user_id,
                                "inactive_3d",
                                "sent",
                                {"unclaimed": unclaimed},
                            )
        except Exception:
            logging.getLogger(__name__).exception("Scheduled reminders failed")

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
    scheduler.add_job(
        scheduled_reminders,
        CronTrigger(hour=10, minute=0),
        id="seller_reminders",
        replace_existing=True,
    )
    scheduler.add_job(
        ensure_biweekly_challenges,
        CronTrigger(day=1, hour=0, minute=5),
        id="challenge_start_1",
        replace_existing=True,
        args=[config],
    )
    scheduler.add_job(
        ensure_biweekly_challenges,
        CronTrigger(day=15, hour=0, minute=5),
        id="challenge_start_15",
        replace_existing=True,
        args=[config],
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
