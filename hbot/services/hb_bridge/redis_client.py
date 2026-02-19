from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Tuple

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None


class RedisStreamClient:
    def __init__(
        self,
        host: str,
        port: int,
        db: int,
        password: Optional[str] = None,
        enabled: bool = True,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._enabled = enabled and redis is not None
        self._client = None
        if not self._enabled:
            self._logger.warning("Redis stream client disabled (enabled=%s redis=%s)", enabled, redis is not None)
            return
        self._client = redis.Redis(host=host, port=port, db=db, password=password, decode_responses=True)

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    def ping(self) -> bool:
        if not self.enabled:
            return False
        try:
            return bool(self._client.ping())
        except Exception:
            return False

    def xadd(self, stream: str, payload: Dict[str, object], maxlen: Optional[int] = None) -> Optional[str]:
        if not self.enabled:
            return None
        body = {"payload": json.dumps(payload)}
        kwargs = {"name": stream, "fields": body}
        if maxlen is not None:
            kwargs.update({"maxlen": maxlen, "approximate": True})
        try:
            return str(self._client.xadd(**kwargs))
        except Exception:
            return None

    def create_group(self, stream: str, group: str) -> None:
        if not self.enabled:
            return
        try:
            self._client.xgroup_create(name=stream, groupname=group, id="$", mkstream=True)
        except Exception:
            # Already exists or stream race.
            pass

    def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> List[Tuple[str, Dict[str, object]]]:
        if not self.enabled:
            return []
        try:
            records = self._client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=count,
                block=block_ms,
            )
        except Exception:
            return []

        out: List[Tuple[str, Dict[str, object]]] = []
        for _stream, entries in records:
            for entry_id, data in entries:
                payload_raw = data.get("payload")
                try:
                    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
                except Exception:
                    payload = {}
                out.append((str(entry_id), payload))
        return out

    def ack(self, stream: str, group: str, entry_id: str) -> None:
        if not self.enabled:
            return
        try:
            self._client.xack(stream, group, entry_id)
        except Exception:
            pass

