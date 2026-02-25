"""State persistence for Paper Engine v2 (DeskStateStore).

Thin wrapper around the existing DailyStateStore for maximum code reuse.
Redis primary, JSON file fallback — same crash-recovery pattern as controller daily state.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from controllers.daily_state_store import DailyStateStore

logger = logging.getLogger(__name__)


class DeskStateStore:
    """Persists PaperDesk portfolio snapshots to Redis + JSON file.

    Reuses DailyStateStore: Redis checked first on load, JSON file as fallback.
    Saves are throttled (30s default) + forced on every fill.

    Persisted: balances, positions, peak equity, funding timestamps.
    NOT persisted: order book, open orders (transient).
    """

    def __init__(
        self,
        file_path: str,
        redis_key: str = "paper_desk:v2:state",
        redis_url: Optional[str] = None,
        save_throttle_s: float = 30.0,
    ):
        self._store = DailyStateStore(
            file_path=file_path,
            redis_key=redis_key,
            redis_url=redis_url,
            save_throttle_s=save_throttle_s,
        )
        self._last_save_ts: float = 0.0

    def save(self, snapshot: Dict[str, Any], now_ts: float, force: bool = False) -> None:
        """Save portfolio snapshot. Throttled unless force=True."""
        self._store.save(snapshot, now_ts, force=force)

    def load(self) -> Optional[Dict[str, Any]]:
        """Load snapshot. Redis first, file fallback. Returns None if nothing saved."""
        return self._store.load()
