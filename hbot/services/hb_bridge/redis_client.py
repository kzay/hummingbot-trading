from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, TypeVar

_T = TypeVar("_T")

from platform_lib.contracts.event_identity import validate_event_identity
from platform_lib.contracts.stream_names import STREAM_RETENTION_MAXLEN

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
        password: str | None = None,
        enabled: bool = True,
        max_connections: int = 4,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._enabled = enabled and redis is not None
        self._host = host
        self._port = port
        self._db = db
        self._password = password
        self._max_connections = max(1, max_connections)
        self._pool: object | None = None
        self._client: object | None = None
        self._last_reconnect_attempt = 0.0
        self._consecutive_failures: int = 0
        self._redis_down_since: float = 0.0
        self._reconnect_attempts_total: int = 0
        self._reconnect_successes_total: int = 0
        self._connection_errors_total: int = 0
        self._connected_since: float = 0.0
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="redis-io")
        self._io_timeout_s: float = 1.0
        self._io_latency_samples: list[float] = []
        self._io_timeout_count: int = 0
        if not self._enabled:
            self._logger.warning("Redis stream client disabled (enabled=%s redis=%s)", enabled, redis is not None)
            return
        self._connect()

    def _connect(self) -> bool:
        """Create or recreate Redis connection with connection pool. Returns True if connected."""
        if not self._enabled or redis is None:
            return False
        try:
            if self._pool is None:
                self._pool = redis.ConnectionPool(
                    host=self._host,
                    port=self._port,
                    db=self._db,
                    password=self._password,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    socket_keepalive=True,
                    max_connections=self._max_connections,
                )
            self._client = redis.Redis(connection_pool=self._pool)
            self._client.ping()
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
            self._connected_since = time.time()
            return True
        except Exception as e:
            self._consecutive_failures += 1
            self._connection_errors_total += 1
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
                self._connection_errors_total += 1
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
                self._connected_since = 0.0
        if redis is None:
            return False
        now = time.time()
        elapsed = now - self._last_reconnect_attempt
        backoff = min(_RECONNECT_BASE_S * (2 ** min(self._consecutive_failures, 5)), _RECONNECT_MAX_S)
        if elapsed < backoff:
            return False
        self._last_reconnect_attempt = now
        self._reconnect_attempts_total += 1
        if self._connect():
            self._reconnect_successes_total += 1
            self._logger.info("Redis reconnected to %s:%s", self._host, self._port)
            return True
        return False

    def _threaded_io(self, fn: Callable[..., _T], *args: Any, fallback: _T, timeout_s: float | None = None) -> _T:
        """Submit a blocking Redis I/O call to the thread pool with timeout protection."""
        effective_timeout = timeout_s if timeout_s is not None else self._io_timeout_s
        t0 = time.perf_counter()
        try:
            future = self._executor.submit(fn, *args)
            result = future.result(timeout=effective_timeout)
            latency_ms = (time.perf_counter() - t0) * 1000
            self._io_latency_samples.append(latency_ms)
            if len(self._io_latency_samples) > 200:
                self._io_latency_samples = self._io_latency_samples[-200:]
            return result
        except FutureTimeoutError:
            self._io_timeout_count += 1
            self._logger.warning("Redis I/O timeout (%.1fs) for %s — returning fallback", effective_timeout, fn.__name__ if hasattr(fn, "__name__") else str(fn))
            return fallback
        except Exception:
            return fallback

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    @property
    def failure_count(self) -> int:
        return self._consecutive_failures

    def health(self) -> dict:
        """Return a snapshot of connection health counters for metrics export."""
        now = time.time()
        connected = self._client is not None and self._connected_since > 0
        samples = self._io_latency_samples
        if samples:
            sorted_s = sorted(samples)
            p50 = sorted_s[len(sorted_s) // 2]
            p99 = sorted_s[min(int(len(sorted_s) * 0.99), len(sorted_s) - 1)]
        else:
            p50 = 0.0
            p99 = 0.0
        return {
            "connected": connected,
            "uptime_s": round(now - self._connected_since, 1) if connected else 0.0,
            "reconnect_attempts_total": self._reconnect_attempts_total,
            "reconnect_successes_total": self._reconnect_successes_total,
            "connection_errors_total": self._connection_errors_total,
            "consecutive_failures": self._consecutive_failures,
            "io_latency_p50_ms": round(p50, 3),
            "io_latency_p99_ms": round(p99, 3),
            "io_timeout_count": self._io_timeout_count,
        }

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

    def _do_xadd(self, kwargs: dict) -> str:
        return str(self._client.xadd(**kwargs))

    def xadd(self, stream: str, payload: dict[str, object], maxlen: int | None = None) -> str | None:
        if not self.enabled and not self._ensure_connected():
            return None
        valid, reason = validate_event_identity(payload)
        if not valid:
            self._logger.warning(
                "Dropped producer event violating identity contract stream=%s event_type=%s reason=%s",
                stream,
                str(payload.get("event_type", "")),
                reason,
            )
            return None
        body = {"payload": json.dumps(payload)}
        kwargs: dict[str, object] = {"name": stream, "fields": body}
        effective_maxlen = maxlen if maxlen is not None else STREAM_RETENTION_MAXLEN.get(stream)
        if effective_maxlen is not None:
            kwargs.update({"maxlen": int(effective_maxlen), "approximate": True})
        try:
            result = self._threaded_io(self._do_xadd, kwargs, fallback=None)
            if result is None:
                return None
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

    def xtrim(self, stream: str, maxlen: int, *, approximate: bool = True) -> int | None:
        if not self.enabled and not self._ensure_connected():
            return None
        safe_maxlen = max(1, int(maxlen))
        try:
            result = self._client.xtrim(name=stream, maxlen=safe_maxlen, approximate=bool(approximate))
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
            return int(result)
        except (RedisConnectionError, OSError) as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis xtrim failed (first failure): %s", e)
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
                self._logger.warning("Redis xtrim failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
            return None

    def create_group(self, stream: str, group: str, *, start_id: str = "$") -> None:
        if not self.enabled and not self._ensure_connected():
            return
        try:
            self._client.xgroup_create(name=stream, groupname=group, id=str(start_id or "$"), mkstream=True)
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

    def _do_xreadgroup(self, kwargs: dict) -> Any:
        return self._client.xreadgroup(**kwargs)

    def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[tuple[str, dict[str, object]]]:
        if not self.enabled and not self._ensure_connected():
            return []
        try:
            rg_kwargs = dict(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=count,
                block=block_ms,
            )
            timeout = max(self._io_timeout_s, (block_ms / 1000.0) + 1.0)
            records = self._threaded_io(self._do_xreadgroup, rg_kwargs, fallback=None, timeout_s=timeout)
            if records is None:
                return []
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

        out: list[tuple[str, dict[str, object]]] = []
        for _stream, entries in records:
            for entry_id, data in entries:
                payload_raw = data.get("payload")
                try:
                    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
                except Exception:
                    payload = {}
                out.append((str(entry_id), payload))
        return out

    def read_group_multi(
        self,
        streams: list[str],
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[tuple[str, str, dict[str, object]]]:
        if not self.enabled and not self._ensure_connected():
            return []
        stream_map = {str(stream): ">" for stream in streams if str(stream).strip()}
        if not stream_map:
            return []
        try:
            records = self._client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams=stream_map,
                count=count,
                block=block_ms,
            )
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
        except (RedisConnectionError, OSError, ConnectionRefusedError) as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis read_group_multi failed (first failure): %s", e)
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
                self._logger.warning("Redis read_group_multi failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
            return []

        out: list[tuple[str, str, dict[str, object]]] = []
        for stream_name, entries in records:
            for entry_id, data in entries:
                payload_raw = data.get("payload")
                try:
                    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
                except Exception:
                    payload = {}
                out.append((str(stream_name), str(entry_id), payload))
        return out

    def read_pending(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 1,
    ) -> list[tuple[str, dict[str, object]]]:
        """Read pending entries for this consumer using XREADGROUP id=0."""
        if not self.enabled and not self._ensure_connected():
            return []
        try:
            records = self._client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: "0"},
                count=count,
                block=block_ms,
            )
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
        except (RedisConnectionError, OSError, ConnectionRefusedError) as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis read_pending failed (first failure): %s", e)
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
                self._logger.warning("Redis read_pending failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
            return []

        out: list[tuple[str, dict[str, object]]] = []
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
        min_idle_ms: int = 120_000,
        count: int = 100,
        start_id: str = "0-0",
    ) -> list[tuple[str, dict[str, object]]]:
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

        out: list[tuple[str, dict[str, object]]] = []
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

    def ack_many(self, stream: str, group: str, entry_ids: list[str]) -> None:
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

    def _do_xrevrange(self, stream: str, count: int) -> Any:
        return self._client.xrevrange(name=stream, max="+", min="-", count=count)

    def read_latest(self, stream: str) -> tuple[str, dict[str, object]] | None:
        """Fetch the latest payload in a stream without consumer-group state changes."""
        if not self.enabled and not self._ensure_connected():
            return None
        try:
            records = self._threaded_io(self._do_xrevrange, stream, 1, fallback=None)
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

    def read_recent(self, stream: str, count: int = 20) -> list[tuple[str, dict[str, object]]]:
        """Fetch recent payloads in reverse order without consumer-group state changes."""
        if not self.enabled and not self._ensure_connected():
            return []
        try:
            records = self._threaded_io(self._do_xrevrange, stream, max(1, int(count)), fallback=None)
            if records is None:
                return []
            out: list[tuple[str, dict[str, object]]] = []
            for entry_id, data in records:
                payload_raw = data.get("payload")
                try:
                    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
                except Exception:
                    payload = {}
                out.append((str(entry_id), payload))
            self._consecutive_failures = 0
            self._redis_down_since = 0.0
            return out
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures == 1:
                self._redis_down_since = time.time()
                self._logger.warning("Redis read_recent failed (first failure): %s", e)
            elif self._consecutive_failures >= 5:
                duration = time.time() - self._redis_down_since
                self._logger.error(
                    "Redis down for %.1fs (%d consecutive failures): %s",
                    duration,
                    self._consecutive_failures,
                    e,
                )
            return []

