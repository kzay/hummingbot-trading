"""State persistence for Paper Engine v2 (DeskStateStore + EventJournal).

DeskStateStore — thin wrapper around DailyStateStore:
  Redis primary, JSON file fallback — same crash-recovery pattern as controller.

EventJournal — append-only JSONL event log alongside snapshots:
  Enables deterministic replay and postmortem analysis.
  Schema: one JSON object per line, always including event_type + ts_ns.
  Recovery: replay journal entries since last snapshot on startup.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from controllers.daily_state_store import DailyStateStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EventJournal — append-only event log
# ---------------------------------------------------------------------------

class EventJournal:
    """Append-only JSONL event log for deterministic replay.

    Each write is a single JSON line flushed immediately to disk.
    On startup, callers can iterate entries since a given snapshot timestamp
    to rebuild state without replaying the full history.

    File is rotated daily (new file per UTC day) to bound size.
    """

    def __init__(self, dir_path: str, prefix: str = "desk_events"):
        self._dir = Path(dir_path)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._prefix = prefix
        self._current_path: Optional[Path] = None
        self._current_fp = None

    def _day_key(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y%m%d")

    def _ensure_open(self) -> None:
        day_key = self._day_key()
        expected_path = self._dir / f"{self._prefix}_{day_key}.jsonl"
        if self._current_path != expected_path:
            self._close_current()
            self._current_path = expected_path
            self._current_fp = expected_path.open("a", encoding="utf-8")

    def _close_current(self) -> None:
        try:
            if self._current_fp is not None:
                self._current_fp.flush()
                self._current_fp.close()
        except Exception:
            pass
        self._current_fp = None

    def append(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Append one event to the journal. Never raises (trading loop safe)."""
        try:
            self._ensure_open()
            entry = {
                "event_type": event_type,
                "ts_ns": time.time_ns(),
                **payload,
            }
            line = json.dumps(entry, default=str) + "\n"
            self._current_fp.write(line)
            self._current_fp.flush()
        except Exception as exc:
            logger.warning("EventJournal.append failed: %s", exc)

    def iter_since(self, min_ts_ns: int = 0) -> Iterator[Dict[str, Any]]:
        """Iterate all journal entries from all files with ts_ns >= min_ts_ns."""
        for path in sorted(self._dir.glob(f"{self._prefix}_*.jsonl")):
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("ts_ns", 0) >= min_ts_ns:
                            yield entry
                    except Exception:
                        pass
            except Exception:
                pass

    def close(self) -> None:
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
        redis_url: Optional[str] = None,
        save_throttle_s: float = 30.0,
        journal_dir: Optional[str] = None,
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
            self._journal: Optional[EventJournal] = EventJournal(journal_dir)
        else:
            # Fall back to dir of state file if journal_dir not given.
            try:
                fallback_dir = str(Path(file_path).parent)
                self._journal = EventJournal(fallback_dir)
            except Exception:
                self._journal = None

    def save(self, snapshot: Dict[str, Any], now_ts: float, force: bool = False) -> None:
        """Save portfolio snapshot. Throttled unless force=True."""
        self._store.save(snapshot, now_ts, force=force)
        # Journal the snapshot event for replay anchoring.
        if self._journal is not None:
            try:
                self._journal.append("desk_snapshot", {"snapshot": snapshot})
            except Exception:
                pass

    def load(self) -> Optional[Dict[str, Any]]:
        """Load snapshot. Redis first, file fallback. Returns None if nothing saved."""
        return self._store.load()

    def journal_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Append an arbitrary event to the journal (for fills, funding, etc.)."""
        if self._journal is not None:
            self._journal.append(event_type, payload)

    def iter_journal(self, min_ts_ns: int = 0) -> Iterator[Dict[str, Any]]:
        """Iterate journal entries for replay/postmortem analysis."""
        if self._journal is not None:
            yield from self._journal.iter_since(min_ts_ns)

    def close(self) -> None:
        if self._journal is not None:
            self._journal.close()
