from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.services.erp import ErpSyncError, fetch_sales, record_sync_error, record_sync_success, upsert_sales

logger = logging.getLogger(__name__)


def setup_scheduler(
    sessionmaker: async_sessionmaker[AsyncSession],
    erp_url: str,
    erp_username: str,
    erp_password: str,
    cron_expr: str,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    trigger = _safe_cron(cron_expr)

    async def _job() -> None:
        async with sessionmaker() as session:
            try:
                sales = await fetch_sales(erp_url, erp_username, erp_password)
                await upsert_sales(session, sales)
                await record_sync_success(session)
                await session.commit()
            except ErpSyncError as exc:
                await record_sync_error(session, str(exc))
                await session.commit()
                logger.exception("ERP sync error")
            except Exception:
                logger.exception("Unexpected error during ERP sync")

    scheduler.add_job(_job, trigger)
    return scheduler


def _safe_cron(expr: str) -> CronTrigger:
    try:
        return CronTrigger.from_crontab(expr)
    except Exception:
        logger.warning("Invalid SYNC_CRON '%s', fallback to */30 * * * *", expr)
        return CronTrigger.from_crontab("*/30 * * * *")
