from pathlib import Path

from bot.config import Config
from bot.db.repo import upsert_erp_sales
from bot.services.erp_client import fetch_erp_sales, normalize_row
from bot.services.time_utils import get_last_closed_month_range


async def sync_erp(config: Config, session_factory) -> int:
    if not config.erp_http_url:
        return 0
    query_path = Path("1cerpsql")
    query = query_path.read_text(encoding="utf-8")
    start, end, month_key = get_last_closed_month_range(config.timezone)
    rows = await fetch_erp_sales(
        config.erp_http_url,
        config.erp_http_user,
        config.erp_http_password,
        query,
        start.strftime("%Y-%m-%d %H:%M:%S"),
        end.strftime("%Y-%m-%d %H:%M:%S"),
        config.erp_timeout_sec,
    )
    normalized = [normalize_row(row, month_key) for row in rows]
    async with session_factory() as session:
        return await upsert_erp_sales(session, normalized)
