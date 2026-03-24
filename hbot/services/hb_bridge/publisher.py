from __future__ import annotations

import logging

from platform_lib.contracts.event_identity import validate_event_identity
from platform_lib.contracts.event_schemas import (
    AuditEvent,
    BotFillEvent,
    MarketDepthSnapshotEvent,
    MarketQuoteEvent,
    MarketSnapshotEvent,
    MarketTradeEvent,
)
from platform_lib.contracts.stream_names import (
    AUDIT_STREAM,
    BOT_TELEMETRY_STREAM,
    MARKET_DATA_STREAM,
    MARKET_DEPTH_STREAM,
    MARKET_QUOTE_STREAM,
    MARKET_TRADE_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient

logger = logging.getLogger(__name__)


class HBEventPublisher:
    def __init__(self, redis_client: RedisStreamClient, producer: str):
        self._redis = redis_client
        self._producer = producer

    @property
    def available(self) -> bool:
        return self._redis.enabled and self._redis.ping()

    def _publish(self, stream: str, payload: dict) -> str | None:
        valid, reason = validate_event_identity(payload)
        if not valid:
            logger.warning(
                "Dropped producer event violating identity contract stream=%s event_type=%s reason=%s",
                stream,
                str(payload.get("event_type", "")),
                reason,
            )
            return None
        return self._redis.xadd(
            stream,
            payload,
            maxlen=STREAM_RETENTION_MAXLEN.get(stream),
        )

    def publish_market_snapshot(self, event: MarketSnapshotEvent) -> str | None:
        event.producer = self._producer
        return self._publish(MARKET_DATA_STREAM, event.model_dump())

    def publish_market_depth(self, event: MarketDepthSnapshotEvent) -> str | None:
        event.producer = self._producer
        return self._publish(MARKET_DEPTH_STREAM, event.model_dump())

    def publish_market_quote(self, event: MarketQuoteEvent) -> str | None:
        event.producer = self._producer
        return self._publish(MARKET_QUOTE_STREAM, event.model_dump())

    def publish_market_trade(self, event: MarketTradeEvent) -> str | None:
        event.producer = self._producer
        return self._publish(MARKET_TRADE_STREAM, event.model_dump())

    def publish_audit(self, event: AuditEvent) -> str | None:
        event.producer = self._producer
        return self._publish(AUDIT_STREAM, event.model_dump())

    def publish_fill(self, event: BotFillEvent) -> str | None:
        """Publish a fill event to BOT_TELEMETRY_STREAM.

        Works for both paper (accounting_source='paper_desk_v2') and live
        (accounting_source='live_connector') fills, making the event_store
        ingestion symmetric regardless of trading mode.
        """
        event.producer = self._producer
        return self._publish(BOT_TELEMETRY_STREAM, event.model_dump())

