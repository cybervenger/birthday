"""Central logging setup used by every module in the pipeline."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from config import LOG_DIR

_CONFIGURED = False


def get_logger(name: str, company: str | None = None) -> logging.Logger:
    """Return a module-scoped logger that writes to console + a shared file."""
    global _CONFIGURED
    logger = logging.getLogger(name)

    if not _CONFIGURED:
        root = logging.getLogger()
        root.setLevel(logging.INFO)

        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(fmt)
        root.addHandler(stream_handler)

        log_file = Path(LOG_DIR) / f"{company or 'pipeline'}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

        # Silence noisy third-party libraries.
        for noisy in ("httpx", "httpcore", "urllib3", "playwright"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

        _CONFIGURED = True

    return logger
