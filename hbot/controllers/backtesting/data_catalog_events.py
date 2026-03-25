"""Publish data catalog change events to the Redis stream."""
from __future__ import annotations

import json
import logging
import time

from platform_lib.contracts.stream_names import DATA_CATALOG_STREAM, STREAM_RETENTION_MAXLEN

logger = logging.getLogger(__name__)


def publish_catalog_update(
    redis_client,
    *,
    exchange: str,
    pair: str,
    resolution: str,
    start_ms: int,
    end_ms: int,
    row_count: int,
    gaps_found: int = 0,
    gaps_repaired: int = 0,
) -> str | None:
    """Publish a ``data_catalog_updated`` event via XADD.

    Returns the stream entry ID on success, ``None`` if *redis_client* is
    ``None`` or the publish fails.
    """
    if redis_client is None:
        logger.debug("No Redis client — skipping data catalog event publish")
        return None

    payload = {
        "event_type": "data_catalog_updated",
        "producer": "data_refresh",
        "exchange": exchange,
        "pair": pair,
        "resolution": resolution,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "row_count": row_count,
        "gaps_found": gaps_found,
        "gaps_repaired": gaps_repaired,
        "timestamp_ms": int(time.time() * 1000),
    }

    maxlen = STREAM_RETENTION_MAXLEN.get(DATA_CATALOG_STREAM, 1000)
    try:
        entry_id = redis_client.xadd(
            DATA_CATALOG_STREAM,
            {"data": json.dumps(payload)},
            maxlen=maxlen,
        )
        logger.info(
            "Published data_catalog_updated for %s/%s/%s → %s",
            exchange, pair, resolution, entry_id,
        )
        return entry_id
    except Exception:
        logger.exception("Failed to publish data catalog event")
        return None
