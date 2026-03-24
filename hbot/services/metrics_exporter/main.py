"""Unified metrics-exporter: runs both bot and control-plane Prometheus exporters
in a single container to reduce resource overhead.

- Bot metrics:          port 9400  /metrics  /health
- Control-plane metrics: port 9401  /metrics  /health
"""
from __future__ import annotations

import logging
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("metrics-exporter")


def _run_bot_exporter() -> None:
    from services.bot_metrics_exporter import main as bot_main
    try:
        bot_main()
    except Exception:
        logger.exception("bot-metrics-exporter crashed")


def _run_control_plane_exporter() -> None:
    from services.control_plane_metrics_exporter import main as cp_main
    try:
        cp_main()
    except Exception:
        logger.exception("control-plane-metrics-exporter crashed")


def main() -> None:
    logger.info("starting unified metrics-exporter (bot=9400, control-plane=9401)")

    t_bot = threading.Thread(target=_run_bot_exporter, daemon=True, name="bot-metrics")
    t_cp = threading.Thread(target=_run_control_plane_exporter, daemon=True, name="cp-metrics")

    t_bot.start()
    t_cp.start()

    t_bot.join()
    t_cp.join()


if __name__ == "__main__":
    main()
