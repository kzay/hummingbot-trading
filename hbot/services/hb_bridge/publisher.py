from __future__ import annotations

from typing import Optional

from services.contracts.event_schemas import AuditEvent, BotFillEvent, MarketSnapshotEvent
from services.contracts.stream_names import (
    AUDIT_STREAM,
    BOT_TELEMETRY_STREAM,
    MARKET_DATA_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient


class HBEventPublisher:
    def __init__(self, redis_client: RedisStreamClient, producer: str):
        self._redis = redis_client
        self._producer = producer

    @property
    def available(self) -> bool:
        return self._redis.enabled and self._redis.ping()

    def publish_market_snapshot(self, event: MarketSnapshotEvent) -> Optional[str]:
        event.producer = self._producer
        return self._redis.xadd(
            MARKET_DATA_STREAM,
            event.model_dump(),
            maxlen=STREAM_RETENTION_MAXLEN.get(MARKET_DATA_STREAM),
        )

    def publish_audit(self, event: AuditEvent) -> Optional[str]:
        event.producer = self._producer
        return self._redis.xadd(
            AUDIT_STREAM,
            event.model_dump(),
            maxlen=STREAM_RETENTION_MAXLEN.get(AUDIT_STREAM),
        )

    def publish_fill(self, event: BotFillEvent) -> Optional[str]:
        """Publish a fill event to BOT_TELEMETRY_STREAM.

        Works for both paper (accounting_source='paper_desk_v2') and live
        (accounting_source='live_connector') fills, making the event_store
        ingestion symmetric regardless of trading mode.
        """
        event.producer = self._producer
        return self._redis.xadd(
            BOT_TELEMETRY_STREAM,
            event.model_dump(),
            maxlen=STREAM_RETENTION_MAXLEN.get(BOT_TELEMETRY_STREAM),
        )

