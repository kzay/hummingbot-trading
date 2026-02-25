"""Dual-backend daily state persistence (Redis + JSON file).

Saves controller daily accounting state to both a Redis hash and a local
JSON file.  On load, Redis is checked first (survives container restart
without volume), then file (survives Redis outage).  This closes the gap
where a restart could lose daily equity/position data when the exchange
API is temporarily unavailable.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

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
        redis_url: Optional[str] = None,
        save_throttle_s: float = 30.0,
    ):
        self._file_path = Path(file_path)
        self._redis_key = redis_key
        self._throttle_s = save_throttle_s
        self._last_save_ts: float = 0.0
        self._redis: Any = None

        if redis_url and _redis_lib is not None:
            try:
                self._redis = _redis_lib.Redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
                logger.info("DailyStateStore: Redis connected for key %s", redis_key)
            except Exception as exc:
                logger.warning("DailyStateStore: Redis unavailable (%s), file-only mode", exc)
                self._redis = None

    def save(self, data: Dict[str, Any], now_ts: float, force: bool = False) -> None:
        """Persist state to both backends (throttled unless *force* is True)."""
        if not force and self._last_save_ts > 0 and (now_ts - self._last_save_ts) < self._throttle_s:
            return

        data["ts_utc"] = datetime.now(timezone.utc).isoformat()
        json_str = json.dumps(data, indent=2, default=str)

        self._save_file(json_str)
        self._save_redis(json_str)
        self._last_save_ts = now_ts

    def load(self) -> Optional[Dict[str, Any]]:
        """Load state — Redis first, fall back to file."""
        data = self._load_redis()
        if data is not None:
            logger.info("DailyStateStore: restored from Redis (%s)", self._redis_key)
            return data
        data = self._load_file()
        if data is not None:
            logger.info("DailyStateStore: restored from file (%s)", self._file_path)
        return data

    def _save_file(self, json_str: str) -> None:
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_path.write_text(json_str, encoding="utf-8")
        except Exception:
            logger.warning("DailyStateStore: file save failed (%s)", self._file_path, exc_info=True)

    def _save_redis(self, json_str: str) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(self._redis_key, json_str, ex=172800)  # 48h TTL
        except Exception:
            logger.warning("DailyStateStore: Redis save failed", exc_info=True)

    def _load_redis(self) -> Optional[Dict[str, Any]]:
        if self._redis is None:
            return None
        try:
            raw = self._redis.get(self._redis_key)
            if raw:
                return json.loads(raw)
        except Exception:
            logger.debug("DailyStateStore: Redis load failed", exc_info=True)
        return None

    def _load_file(self) -> Optional[Dict[str, Any]]:
        if not self._file_path.exists():
            return None
        try:
            return json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("DailyStateStore: file load failed (%s)", self._file_path, exc_info=True)
            return None
