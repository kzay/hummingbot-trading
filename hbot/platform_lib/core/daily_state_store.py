"""Dual-backend daily state persistence (Redis + JSON file).

Saves controller daily accounting state to both a Redis hash and a local
JSON file.  On load, Redis is checked first (survives container restart
without volume), then file (survives Redis outage).  This closes the gap
where a restart could lose daily equity/position data when the exchange
API is temporarily unavailable.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import tempfile
import threading

try:
    import orjson as _orjson
except ImportError:  # pragma: no cover
    _orjson = None  # type: ignore[assignment]
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import redis as _redis_lib
except ImportError:
    _redis_lib = None


class DailyStateStore:
    """Belt-and-suspenders persistence for daily accounting state."""

    def __init__(
        self,
        file_path: str,
        redis_key: str,
        redis_url: str | None = None,
        save_throttle_s: float = 30.0,
    ):
        self._file_path = Path(file_path)
        self._redis_key = redis_key
        self._throttle_s = save_throttle_s
        self._last_save_ts: float = 0.0
        self._redis: Any = None
        self._bg_thread: threading.Thread | None = None
        self._needs_fsync: bool = False
        self._lock = threading.Lock()
        atexit.register(self._atexit_join)

        if redis_url and _redis_lib is not None:
            try:
                self._redis = _redis_lib.Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    socket_keepalive=True,
                )
                self._redis.ping()
                logger.info("DailyStateStore: Redis connected for key %s", redis_key)
            except Exception as exc:
                logger.warning("DailyStateStore: Redis unavailable (%s), file-only mode", exc)
                self._redis = None

    def save(self, data: dict[str, Any], now_ts: float, force: bool = False) -> None:
        """Persist state to both backends (throttled unless *force* is True).

        Serialization happens on the calling thread for snapshot consistency.
        Forced saves write the file synchronously (fast atomic rename to page
        cache) so the data is immediately readable, then defer os.fsync() and
        Redis write to a background thread to avoid blocking the tick loop.
        Throttled saves defer everything to a background thread.
        """
        with self._lock:
            if not force and self._last_save_ts > 0 and (now_ts - self._last_save_ts) < self._throttle_s:
                return

            data["ts_utc"] = datetime.now(UTC).isoformat()
            json_str = _orjson.dumps(data, default=str, option=_orjson.OPT_INDENT_2).decode() if _orjson else json.dumps(data, indent=2, default=str)
            self._last_save_ts = now_ts

            if force:
                # Forced save (fill path): write file synchronously for immediate
                # readability, then defer fsync + Redis to background.
                self._join_pending_save_locked()
                self._save_file(json_str, fsync=False)
                self._needs_fsync = True

                def _deferred():
                    self._fsync_file()
                    self._save_redis(json_str)

                t = threading.Thread(target=_deferred, daemon=True)
                self._bg_thread = t
                t.start()
                t.join(timeout=5.0)
                if t.is_alive():
                    logger.warning(
                        "DailyStateStore: force-flush bg thread still alive after 5s (%s)",
                        self._redis_key,
                    )
                return

            if self._bg_thread is not None and self._bg_thread.is_alive():
                logger.debug("DailyStateStore: throttled save dropped — bg thread still running (%s)", self._redis_key)
                return

            def _write():
                self._save_file(json_str, fsync=True)
                self._save_redis(json_str)

            self._bg_thread = threading.Thread(target=_write, daemon=True)
            self._bg_thread.start()

    def join(self) -> None:
        """Wait for any in-flight background save to complete (public API)."""
        self._join_pending_save()

    def _atexit_join(self) -> None:
        """Best-effort join at process exit so daemon threads can finish fsync."""
        try:
            self._join_pending_save()
        except Exception:  # atexit: swallow all errors during shutdown
            pass

    def _join_pending_save(self) -> None:
        """Wait for any in-flight background save to complete."""
        with self._lock:
            self._join_pending_save_locked()

    def _join_pending_save_locked(self) -> None:
        """Wait for pending save — caller must hold self._lock."""
        t = self._bg_thread
        if t is not None and t.is_alive():
            t.join(timeout=5.0)
            if t.is_alive():
                logger.warning("DailyStateStore: bg save thread still alive after 5s join timeout (%s)", self._redis_key)

    def load(self) -> dict[str, Any] | None:
        """Load state — pick freshest between Redis and file by ts_utc."""
        self._join_pending_save()
        redis_data = self._load_redis()
        file_data = self._load_file()

        if redis_data is None and file_data is None:
            return None
        if redis_data is None:
            logger.info("DailyStateStore: restored from file (%s)", self._file_path)
            return file_data
        if file_data is None:
            logger.info("DailyStateStore: restored from Redis (%s)", self._redis_key)
            return redis_data

        redis_ts = str(redis_data.get("ts_utc", ""))
        file_ts = str(file_data.get("ts_utc", ""))
        if file_ts > redis_ts:
            logger.info(
                "DailyStateStore: file is newer (file=%s, redis=%s), restored from file (%s)",
                file_ts, redis_ts, self._file_path,
            )
            return file_data
        logger.info(
            "DailyStateStore: restored from Redis (redis=%s, file=%s) (%s)",
            redis_ts, file_ts, self._redis_key,
        )
        return redis_data

    def clear(self) -> None:
        """Best-effort delete of both persisted backends."""
        self._join_pending_save()
        self._clear_redis()
        self._clear_file()

    def _save_file(self, json_str: str, *, fsync: bool = True) -> None:
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._file_path.parent),
                suffix=".tmp",
                prefix=".daily_state_",
            )
            try:
                os.write(fd, json_str.encode("utf-8"))
                if fsync:
                    os.fsync(fd)
                    self._needs_fsync = False
            finally:
                os.close(fd)
            os.replace(tmp_path, str(self._file_path))
        except Exception:
            logger.warning("DailyStateStore: file save failed (%s)", self._file_path, exc_info=True)

    def _fsync_file(self) -> None:
        """Fsync the state file if a deferred fsync is pending."""
        if not self._needs_fsync:
            return
        try:
            if self._file_path.exists():
                fd = os.open(str(self._file_path), os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
                self._needs_fsync = False
        except Exception:
            logger.warning("DailyStateStore: deferred fsync failed (%s)", self._file_path, exc_info=True)

    def _save_redis(self, json_str: str) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(self._redis_key, json_str, ex=172800)  # 48h TTL
        except Exception:
            logger.warning("DailyStateStore: Redis save failed", exc_info=True)

    def _load_redis(self) -> dict[str, Any] | None:
        if self._redis is None:
            return None
        try:
            raw = self._redis.get(self._redis_key)
            if raw:
                return _orjson.loads(raw) if _orjson else json.loads(raw)
        except Exception:
            logger.debug("DailyStateStore: Redis load failed", exc_info=True)
        return None

    def _load_file(self) -> dict[str, Any] | None:
        if not self._file_path.exists():
            return None
        try:
            _t = self._file_path.read_text(encoding="utf-8")
            return _orjson.loads(_t) if _orjson else json.loads(_t)
        except Exception:
            logger.warning("DailyStateStore: file load failed (%s)", self._file_path, exc_info=True)
            return None

    def _clear_redis(self) -> None:
        if self._redis is None:
            return
        try:
            self._redis.delete(self._redis_key)
        except Exception:
            logger.warning("DailyStateStore: Redis clear failed", exc_info=True)

    def _clear_file(self) -> None:
        try:
            if self._file_path.exists():
                self._file_path.unlink()
        except Exception:
            logger.warning("DailyStateStore: file clear failed (%s)", self._file_path, exc_info=True)
