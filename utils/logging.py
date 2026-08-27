import os
import logging
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "guardian.log")


def setup_logging(enabled: bool = True, debug: bool = False):
    os.makedirs(LOG_DIR, exist_ok=True)
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level if enabled else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )


def log_event(event: str, level: str = "info"):
    logger = logging.getLogger("guardian")
    log_func = getattr(logger, level, logger.info)
    log_func(event)
