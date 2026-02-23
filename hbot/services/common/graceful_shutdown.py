"""Shared graceful shutdown handler for all long-running services.

Usage::

    from services.common.graceful_shutdown import ShutdownHandler

    shutdown = ShutdownHandler()
    while not shutdown.requested:
        do_work()
        time.sleep(interval)
    shutdown.log_exit()
"""
from __future__ import annotations

import logging
import signal
import time

logger = logging.getLogger(__name__)


class ShutdownHandler:
    """Installs ``SIGTERM``/``SIGINT`` handlers and exposes a stop flag.

    Services check ``shutdown.requested`` in their main loop and exit
    cleanly when it becomes ``True``.
    """

    def __init__(self) -> None:
        self._requested = False
        self._signal_name: str = ""
        self._start_ts = time.time()
        signal.signal(signal.SIGTERM, self._handle)
        signal.signal(signal.SIGINT, self._handle)

    def _handle(self, signum: int, _frame: object) -> None:
        self._signal_name = signal.Signals(signum).name
        self._requested = True
        logger.info("Received %s — initiating graceful shutdown", self._signal_name)

    @property
    def requested(self) -> bool:
        return self._requested

    def log_exit(self) -> None:
        elapsed = time.time() - self._start_ts
        logger.info(
            "Service exiting after %.1fs (signal=%s)",
            elapsed,
            self._signal_name or "none",
        )
