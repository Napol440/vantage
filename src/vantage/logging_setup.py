"""Logging setup: console + optional rotating file handler."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

from .config import Config

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

_configured = False


def setup_logging(cfg: Config, console_level: Optional[str] = None) -> None:
    """Configure root logging once. Idempotent across calls."""
    global _configured
    if _configured:
        return

    level = getattr(logging, (console_level or cfg.logging.level).upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    if cfg.logging.to_file:
        log_file = cfg.logging.file
        try:
            parent = os.path.dirname(log_file)
            if parent:
                os.makedirs(parent, exist_ok=True)
            fh = RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            fh.setLevel(level)
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except OSError:
            root.warning("Could not open log file %s; logging to console only.", log_file)

    _configured = True
