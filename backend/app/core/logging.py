from __future__ import annotations

import logging
import sys

from app.core.config import get_settings


def configure_logging() -> None:
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("pyogrio", "fiona", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
