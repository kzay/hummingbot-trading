"""State persistence for Paper Engine v2 (DeskStateStore + EventJournal).

DeskStateStore — thin wrapper around DailyStateStore:
  Redis primary, JSON file fallback — same crash-recovery pattern as controller.

EventJournal — append-only JSONL event log alongside snapshots:
  Enables deterministic replay and postmortem analysis.
  Schema: one JSON object per line, always including event_type + ts_ns.
  Recovery: replay journal entries since last snapshot on startup.
"""
from __future__ import annotations

import atexit
import json
import logging
import threading
import time

try:
    import orjson as _orjson
except ImportError:  # pragma: no cover
    _orjson = None  # type: ignore[assignment]
from collections.abc import Iterator
from datetime import UTC
from pathlib import Path
from typing import Any

from platform_lib.core.daily_state_store import DailyStateStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EventJournal — append-only event log
# ---------------------------------------------------------------------------

class EventJournal:
    """Append-only JSONL event log for deterministic replay.

    Writes are buffered and flushed to disk every *flush_interval_s* seconds
    (default 0.1s) to reduce I/O in the hot path.  A flush is also forced on
    close() so no data is silently lost during graceful shutdown.

    File is rotated daily (new file per timezone.utc day) to bound size.
    """

    # Event types that trigger immediate sync flush (high-value events).
    _CRITICAL_EVENT_TYPES = frozenset({"order_filled", "forced_liquidation", "position_changed"})

    def __init__(self, dir_path: str, prefix: str = "desk_events", flush_interval_s: float = 0.1):
        self._dir = Path(dir_path)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._prefix = prefix
        self._current_path: Path | None = None
        self._current_fp = None
        self._flush_interval_s = flush_interval_s
        self._buffer: list[str] = []
        self._lock = threading.Lock()
        self._flush_timer: threading.Timer | None = None
        atexit.register(self.flush_sync)

    def _day_key(self) -> str:
        from datetime import datetime
        return datetime.now(UTC).strftime("%Y%m%d")

    def _ensure_open(self) -> None:
        day_key = self._day_key()
        expected_path = self._dir / f"{self._prefix}_{day_key}.jsonl"
        if self._current_path != expected_path:
            self._flush_buffer()
            self._close_current()
            self._current_path = expected_path
            self._current_fp = expected_path.open("a", encoding="utf-8")

    def _close_current(self) -> None:
        try:
            if self._current_fp is not None:
                self._current_fp.flush()
                self._current_fp.close()
        except Exception as exc:
            logger.warning("EventJournal._close_current failed: %s", exc)
        self._current_fp = None

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        """Append one event to the journal. Never raises (trading loop safe)."""
        try:
            self._ensure_open()
            entry = {
                "event_type": event_type,
                "ts_ns": time.time_ns(),
                **payload,
            }
            line = (_orjson.dumps(entry, default=str).decode() if _orjson else json.dumps(entry, default=str)) + "\n"
            with self._lock:
                self._buffer.append(line)
                if self._flush_timer is None:
                    self._flush_timer = threading.Timer(self._flush_interval_s, self._flush_buffer)
                    self._flush_timer.daemon = True
                    self._flush_timer.start()
            # Immediately flush critical events (fills, liquidations) to prevent data loss.
            if event_type in self._CRITICAL_EVENT_TYPES:
                self._flush_buffer()
        except Exception as exc:
            logger.warning("EventJournal.append failed: %s", exc)

    def flush_sync(self) -> None:
        """Synchronously drain buffer and write to disk. Safe to call from atexit."""
        try:
            self._flush_buffer()
            self._close_current()
        except Exception as exc:
            logger.warning("EventJournal.flush_sync failed: %s", exc)

    def _flush_buffer(self) -> None:
        """Write buffered lines to disk. Called by timer or explicitly."""
        with self._lock:
            lines = self._buffer[:]
            self._buffer.clear()
            if self._flush_timer is not None:
                self._flush_timer.cancel()
                self._flush_timer = None
        if not lines or self._current_fp is None:
            return
        try:
            self._current_fp.writelines(lines)
            self._current_fp.flush()
        except Exception as exc:
            logger.warning("EventJournal._flush_buffer failed: %s", exc)

    def iter_since(self, min_ts_ns: int = 0) -> Iterator[dict[str, Any]]:
        """Iterate all journal entries from all files with ts_ns >= min_ts_ns."""
        self._flush_buffer()
        for path in sorted(self._dir.glob(f"{self._prefix}_*.jsonl")):
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = _orjson.loads(line) if _orjson else json.loads(line)
                        if entry.get("ts_ns", 0) >= min_ts_ns:
                            yield entry
                    except Exception:
                        logger.warning("corrupt journal line in %s: %s", path.name, line[:80])
            except Exception as exc:
                logger.warning("failed to read journal file %s: %s", path, exc)

    def close(self) -> None:
        self._flush_buffer()
        self._close_current()


# ---------------------------------------------------------------------------
# DeskStateStore — snapshot persistence (backward-compatible wrapper)
# ---------------------------------------------------------------------------

class DeskStateStore:
    """Persists PaperDesk portfolio snapshots to Redis + JSON file.

    Reuses DailyStateStore: Redis checked first on load, JSON file as fallback.
    Saves are throttled (30s default) + forced on every fill.

    Persisted: balances, positions, peak equity, funding timestamps.
    NOT persisted: order book, open orders (transient).

    EventJournal is maintained alongside snapshots for replay/postmortem
    but is NOT required for normal operation.
    """

    def __init__(
        self,
        file_path: str,
        redis_key: str = "paper_desk:v2:state",
        redis_url: str | None = None,
        save_throttle_s: float = 30.0,
        journal_dir: str | None = None,
    ):
        self._store = DailyStateStore(
            file_path=file_path,
            redis_key=redis_key,
            redis_url=redis_url,
            save_throttle_s=save_throttle_s,
        )
        self._last_save_ts: float = 0.0
        # Optional event journal (enabled when journal_dir is provided).
        if journal_dir:
            self._journal: EventJournal | None = EventJournal(journal_dir)
        else:
            # Fall back to dir of state file if journal_dir not given.
            try:
                fallback_dir = str(Path(file_path).parent)
                self._journal = EventJournal(fallback_dir)
            except Exception:
                self._journal = None

    def save(self, snapshot: dict[str, Any], now_ts: float, force: bool = False) -> None:
        """Save portfolio snapshot. Throttled unless force=True."""
        self._store.save(snapshot, now_ts, force=force)
        # Journal the snapshot event for replay anchoring.
        if self._journal is not None:
            try:
                self._journal.append("desk_snapshot", {"snapshot": snapshot})
            except Exception as exc:
                logger.warning("DeskStateStore journal snapshot failed: %s", exc)

    def load(self) -> dict[str, Any] | None:
        """Load snapshot. Redis first, file fallback. Returns None if nothing saved."""
        return self._store.load()

    def clear(self) -> None:
        """Best-effort delete of persisted snapshot backends."""
        self._store.clear()

    def journal_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Append an arbitrary event to the journal (for fills, funding, etc.)."""
        if self._journal is not None:
            self._journal.append(event_type, payload)

    def iter_journal(self, min_ts_ns: int = 0) -> Iterator[dict[str, Any]]:
        """Iterate journal entries for replay/postmortem analysis."""
        if self._journal is not None:
            yield from self._journal.iter_since(min_ts_ns)

    def close(self) -> None:
        self._store.join()
        if self._journal is not None:
            self._journal.close()
