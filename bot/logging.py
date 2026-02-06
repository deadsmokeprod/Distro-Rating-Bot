import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_PATH = Path("logs/bot.log")


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = RotatingFileHandler(LOG_PATH, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.addHandler(handler)
    logger.addHandler(stream_handler)
