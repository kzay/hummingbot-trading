from __future__ import annotations

import time
from typing import Dict, List, Set, Tuple

from services.contracts.event_schemas import ExecutionIntentEvent
from services.contracts.stream_names import (
    DEAD_LETTER_STREAM,
    EXECUTION_INTENT_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient


class HBIntentConsumer:
    def __init__(
        self,
        redis_client: RedisStreamClient,
        group: str,
        consumer_name: str,
        dedup_ttl_sec: int = 300,
    ) -> None:
        self._redis = redis_client
        self._group = group
        self._consumer_name = consumer_name
        self._dedup_ttl = dedup_ttl_sec
        self._seen: Dict[str, float] = {}
        self._redis.create_group(EXECUTION_INTENT_STREAM, group)

    def _cleanup_seen(self) -> None:
        cutoff = time.time() - self._dedup_ttl
        self._seen = {k: ts for k, ts in self._seen.items() if ts >= cutoff}

    def _is_seen(self, event_id: str) -> bool:
        return event_id in self._seen

    def _mark_seen(self, event_id: str) -> None:
        self._seen[event_id] = time.time()

    def poll(self, count: int = 20, block_ms: int = 1000) -> List[Tuple[str, ExecutionIntentEvent]]:
        self._cleanup_seen()
        entries = self._redis.read_group(
            stream=EXECUTION_INTENT_STREAM,
            group=self._group,
            consumer=self._consumer_name,
            count=count,
            block_ms=block_ms,
        )
        out: List[Tuple[str, ExecutionIntentEvent]] = []
        seen_in_batch: Set[str] = set()
        now_ms = int(time.time() * 1000)
        for entry_id, payload in entries:
            try:
                event = ExecutionIntentEvent(**payload)
            except Exception:
                self._redis.xadd(
                    DEAD_LETTER_STREAM,
                    {"reason": "schema_validation", "entry_id": entry_id, "payload": str(payload)},
                    maxlen=STREAM_RETENTION_MAXLEN.get(DEAD_LETTER_STREAM),
                )
                self._redis.ack(EXECUTION_INTENT_STREAM, self._group, entry_id)
                continue
            # Drop duplicate intents both across prior acked/rejected events and within the same poll batch.
            if self._is_seen(event.event_id) or event.event_id in seen_in_batch:
                self._redis.ack(EXECUTION_INTENT_STREAM, self._group, entry_id)
                continue
            if event.expires_at_ms is not None and now_ms > event.expires_at_ms:
                self._redis.xadd(
                    DEAD_LETTER_STREAM,
                    {"reason": "expired_intent", "entry_id": entry_id, "event_id": event.event_id},
                    maxlen=STREAM_RETENTION_MAXLEN.get(DEAD_LETTER_STREAM),
                )
                self._mark_seen(event.event_id)
                self._redis.ack(EXECUTION_INTENT_STREAM, self._group, entry_id)
                continue
            seen_in_batch.add(event.event_id)
            out.append((entry_id, event))
        return out

    def ack(self, entry_id: str, event_id: str) -> None:
        self._mark_seen(event_id)
        self._redis.ack(EXECUTION_INTENT_STREAM, self._group, entry_id)

    def reject(self, entry_id: str, event_id: str, reason: str) -> None:
        self._redis.xadd(
            DEAD_LETTER_STREAM,
            {"reason": reason, "entry_id": entry_id, "event_id": event_id},
            maxlen=STREAM_RETENTION_MAXLEN.get(DEAD_LETTER_STREAM),
        )
        self.ack(entry_id, event_id)

