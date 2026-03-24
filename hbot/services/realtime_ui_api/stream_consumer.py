from __future__ import annotations

import logging
import os
import threading
import time
from typing import TYPE_CHECKING

from platform_lib.contracts.stream_names import (
    BOT_TELEMETRY_STREAM,
    DEFAULT_CONSUMER_GROUP,
    MARKET_DATA_STREAM,
    MARKET_DEPTH_STREAM,
    MARKET_QUOTE_STREAM,
    PAPER_EXCHANGE_EVENT_STREAM,
)
from services.hb_bridge.redis_client import RedisStreamClient
from services.realtime_ui_api._helpers import RealtimeApiConfig

if TYPE_CHECKING:
    from services.realtime_ui_api.state import RealtimeState

logger = logging.getLogger(__name__)


class StreamWorker:
    def __init__(self, cfg: RealtimeApiConfig, state: RealtimeState):
        self._cfg = cfg
        self._state = state
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ack_fail_count = 0
        self._client = RedisStreamClient(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD", "") or None,
            enabled=os.getenv("EXT_SIGNAL_RISK_ENABLED", "true").strip().lower() in {"1", "true", "yes"},
        )
        self._streams = [
            MARKET_DATA_STREAM,
            MARKET_QUOTE_STREAM,
            MARKET_DEPTH_STREAM,
            BOT_TELEMETRY_STREAM,
            PAPER_EXCHANGE_EVENT_STREAM,
        ]

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="realtime-ui-api-stream-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    @property
    def redis_available(self) -> bool:
        return self._client.enabled and self._client.ping()

    def _run(self) -> None:
        if not self._client.enabled:
            logger.warning("realtime_ui_api stream worker started with Redis disabled; fallback mode only.")
            return
        for stream in self._streams:
            self._client.create_group(stream, self._cfg.consumer_group or DEFAULT_CONSUMER_GROUP)
        while not self._stop.is_set():
            processed = 0
            for stream in self._streams:
                entries = self._client.read_group(
                    stream=stream,
                    group=self._cfg.consumer_group or DEFAULT_CONSUMER_GROUP,
                    consumer=self._cfg.consumer_name or "realtime-ui-api-1",
                    count=200,
                    block_ms=max(1, self._cfg.poll_ms),
                )
                for entry_id, payload in entries:
                    if not isinstance(payload, dict):
                        continue
                    try:
                        self._state.process(stream=stream, entry_id=entry_id, payload=payload)
                    except Exception:
                        logger.warning("stream_consumer: failed to process %s entry %s", stream, entry_id, exc_info=True)
                    try:
                        self._client.ack(stream, self._cfg.consumer_group or DEFAULT_CONSUMER_GROUP, entry_id)
                    except Exception:
                        self._ack_fail_count += 1
                        logger.warning("stream_consumer: ack failed for %s entry %s (total_failures=%d)", stream, entry_id, self._ack_fail_count, exc_info=True)
                    processed += 1
            if processed == 0:
                time.sleep(0.05)
