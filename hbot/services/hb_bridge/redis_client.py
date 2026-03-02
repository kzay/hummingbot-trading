from __future__ import annotations

import json
import logging
import time
from typing import Dict, List, Optional, Tuple

try:
    import redis  # type: ignore
    from redis.exceptions import ConnectionError as RedisConnectionError
except Exception:  # pragma: no cover
    redis = None
    RedisConnectionError = Exception

# Reconnect backoff: max 30s, exponential
_RECONNECT_BASE_S = 1.0
_RECONNECT_MAX_S = 30.0


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
        self._host = host
        self._port = port
        self._db = db
        self._password = password
        self._client: Optional[object] = None
        self._last_reconnect_attempt = 0.0
        self._consecutive_failures: int = 0
        self._redis_down_since: float = 0.0
        if not self._enabled:
            self._logger.warning("Redis stream client disabled (enabled=%s redis=%s)", enabled, redis is not None)
            return
        self._connect()

    def _connect(self) -> bool:
        """Create or recreate Redis connection. Returns True if connected."""
        if not self._enabled or redis is None:
            return False
        try:
            self._client = redis.Redis(
                host=self._host,
                port=self._port,
                db=self._db,
                password=self._password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                socket_keepalive=True,
            )
            self._client.ping()
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
            return True
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis connect failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
            self._client = None
            return False

    def _ensure_connected(self) -> bool:
        """Reconnect if connection failed. Returns True if ready for operations."""
        if not self._enabled:
            return False
        if self._client is not None:
            try:
                self._client.ping()
                self._consecutive_failures = 0
                self._redis_down_since = 0.0
                return True
            except Exception as e:
                self._consecutive_failures += 1
                if self._consecutive_failures == 1:
                    self._redis_down_since = time.time()
                    self._logger.warning("Redis ping failed (first failure): %s", e)
                elif self._consecutive_failures >= 5:
                    duration = time.time() - self._redis_down_since
                    self._logger.error(
                        "Redis down for %.1fs (%d consecutive failures): %s",
                        duration,
                        self._consecutive_failures,
                        e,
                    )
                self._client = None
        if redis is None:
            return False
        now = time.time()
        elapsed = now - self._last_reconnect_attempt
        if elapsed < _RECONNECT_BASE_S:
            return False
        backoff = min(_RECONNECT_BASE_S * (2 ** min(5, int(elapsed / _RECONNECT_BASE_S))), _RECONNECT_MAX_S)
        self._last_reconnect_attempt = now
        if self._connect():
            self._logger.info("Redis reconnected to %s:%s", self._host, self._port)
            return True
        return False

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    @property
    def failure_count(self) -> int:
        return self._consecutive_failures

    def ping(self) -> bool:
        if not self.enabled:
            return self._ensure_connected()
        try:
            result = bool(self._client.ping())
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
            return result
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis ping failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
            return self._ensure_connected()

    def xadd(self, stream: str, payload: Dict[str, object], maxlen: Optional[int] = None) -> Optional[str]:
        if not self.enabled and not self._ensure_connected():
            return None
        body = {"payload": json.dumps(payload)}
        kwargs: Dict[str, object] = {"name": stream, "fields": body}
        if maxlen is not None:
            kwargs.update({"maxlen": maxlen, "approximate": True})
        try:
            result = str(self._client.xadd(**kwargs))
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
            return result
        except (RedisConnectionError, OSError) as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis xadd failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
            self._client = None
            return None
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis xadd failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
            return None

    def create_group(self, stream: str, group: str) -> None:
        if not self.enabled and not self._ensure_connected():
            return
        try:
            self._client.xgroup_create(name=stream, groupname=group, id="$", mkstream=True)
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
        except Exception as e:
            # BUSYGROUP is expected on restarts; it's not a connectivity failure.
            if "BUSYGROUP" in str(e).upper():
                self._consecutive_failures = 0
                self._redis_down_since = 0.0
                self._logger.debug("Redis consumer group already exists for stream=%s group=%s", stream, group)
                return
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis create_group failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )

    def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> List[Tuple[str, Dict[str, object]]]:
        if not self.enabled and not self._ensure_connected():
            return []
        try:
            records = self._client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=count,
                block=block_ms,
            )
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
        except (RedisConnectionError, OSError, ConnectionRefusedError) as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis read_group failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
            self._client = None
            return []
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis read_group failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
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

    def claim_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        min_idle_ms: int = 30_000,
        count: int = 100,
        start_id: str = "0-0",
    ) -> List[Tuple[str, Dict[str, object]]]:
        """Claim stale pending entries for the given consumer group.

        Uses XAUTOCLAIM semantics when available. Returns claimed rows in the same
        structure as ``read_group`` for drop-in processing.
        """
        if not self.enabled and not self._ensure_connected():
            return []
        try:
            raw = self._client.xautoclaim(
                name=stream,
                groupname=group,
                consumername=consumer,
                min_idle_time=max(1, int(min_idle_ms)),
                start_id=str(start_id or "0-0"),
                count=max(1, int(count)),
            )
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis claim_pending failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
            return []

        entries = []
        # redis-py return shapes differ by version:
        #   (next_start_id, [(entry_id, {payload})], [deleted_ids]) or
        #   (next_start_id, [(entry_id, {payload})])
        if isinstance(raw, tuple):
            if len(raw) >= 2 and isinstance(raw[1], list):
                entries = raw[1]
        elif isinstance(raw, list) and len(raw) >= 2 and isinstance(raw[1], list):
            entries = raw[1]

        out: List[Tuple[str, Dict[str, object]]] = []
        for entry_id, data in entries:
            payload_raw = data.get("payload") if isinstance(data, dict) else None
            try:
                payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
            except Exception:
                payload = {}
            out.append((str(entry_id), payload))
        return out

    def ack(self, stream: str, group: str, entry_id: str) -> None:
        if not self.enabled and not self._ensure_connected():
            return
        try:
            self._client.xack(stream, group, entry_id)
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis ack failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )

    def ack_many(self, stream: str, group: str, entry_ids: List[str]) -> None:
        ids = [str(entry_id) for entry_id in entry_ids if str(entry_id).strip()]
        if not ids:
            return
        if not self.enabled and not self._ensure_connected():
            return
        try:
            self._client.xack(stream, group, *ids)
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis ack_many failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )

    def read_latest(self, stream: str) -> Optional[Tuple[str, Dict[str, object]]]:
        """Fetch the latest payload in a stream without consumer-group state changes."""
        if not self.enabled and not self._ensure_connected():
            return None
        try:
            records = self._client.xrevrange(name=stream, max="+", min="-", count=1)
            if not records:
                return None
            entry_id, data = records[0]
            payload_raw = data.get("payload")
            try:
                payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
            except Exception:
                payload = {}
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
            return str(entry_id), payload
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis read_latest failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
            return None

