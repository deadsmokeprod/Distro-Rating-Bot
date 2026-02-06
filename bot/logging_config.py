import logging
import os


def setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler("logs/bot.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
