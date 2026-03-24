"""Shared logging configuration for all services and controllers.

Usage::

    from services.common.logging_config import configure_logging
    configure_logging()
"""
from __future__ import annotations

import logging
import sys


def configure_logging(
    level: int = logging.INFO,
    fmt: str = "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt: str = "%Y-%m-%dT%H:%M:%S%z",
) -> None:
    """Set up root logging with a consistent format.

    Call once at service entry point (``if __name__ == "__main__"``).
    """
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    root.setLevel(level)
    root.addHandler(handler)
