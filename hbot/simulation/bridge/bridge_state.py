"""Bridge state container — single process-wide mutable singleton.

All mutable bridge state (Redis client, cursors, caches, guard state) is
encapsulated in ``BridgeState``. Tests can call ``reset()`` for clean isolation.

CONCURRENCY CONTRACT:
- Owner: main bridge tick loop (single-threaded HB event loop).
- ``_bridge_state`` must only be mutated from the owner thread.
- ``reset()`` must only be called when no bridge tick is in progress.
- Set ``PAPER_DEBUG_THREAD_CHECKS=1`` to enable runtime thread-identity assertions.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from platform_lib.core.latency_tracker import JsonLatencyTracker

logger = logging.getLogger(__name__)

_DEBUG_THREAD_CHECKS = os.getenv("PAPER_DEBUG_THREAD_CHECKS", "").lower() in {"1", "true", "yes"}
_OWNER_THREAD_ID: int | None = None


def _assert_owner_thread(label: str = "bridge_state") -> None:
    """In debug mode, assert that mutation happens on the owner thread."""
    global _OWNER_THREAD_ID
    if not _DEBUG_THREAD_CHECKS:
        return
    tid = threading.get_ident()
    if _OWNER_THREAD_ID is None:
        _OWNER_THREAD_ID = tid
        return
    if tid != _OWNER_THREAD_ID:
        raise RuntimeError(
            f"{label}: mutation from thread {tid} ({threading.current_thread().name}), "
            f"expected owner thread {_OWNER_THREAD_ID}"
        )


class BridgeState:
    """Encapsulates all mutable bridge state (Redis, signal cursor, guard state, ML model).

    A single process-wide instance ``_bridge_state`` replaces the former
    module-level globals. Tests can call ``reset()`` instead of reaching into
    six separate module attributes.

    CONCURRENCY CONTRACT:
    - Owner: main bridge tick loop (single-threaded HB event loop).
    - _REDIS_IO_POOL threads may read ``redis_client`` and caches but must
      NOT mutate dicts/sets directly — submit results back to the main loop.
    - ``reset()`` must only be called when no bridge tick is in progress
      (test teardown, or before ``install_paper_desk_bridge``).
    - Thread-safe members: ``redis_client`` (redis-py is thread-safe),
      ``_LATENCY_TRACKER`` (has its own Lock).
    """

    __slots__ = (
        "active_cancel_all_command_cache",
        "active_cancel_command_cache",
        "active_failure_streak_by_key",
        "active_submit_order_cache",
        "adverse_model",
        "adverse_model_loaded",
        "adverse_model_path",
        "last_ml_features_id",
        "last_paper_exchange_event_id",
        "last_signal_id",
        "paper_exchange_auto_mode_by_instance",
        "paper_exchange_auto_mode_updated_ms_by_instance",
        "paper_exchange_cursor_initialized",
        "paper_exchange_mode_warned_instances",
        "paper_exchange_seen_event_ids",
        "prev_guard_states",
        "redis_client",
        "redis_init_done",
        "sync_confirmed_keys",
        "sync_requested_at_ms_by_key",
        "sync_state_published_keys",
        "sync_timeout_hard_stop_keys",
    )

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        _assert_owner_thread("BridgeState.reset")
        self._close_redis()
        self.redis_client: Any | None = None
        self.redis_init_done: bool = False
        self.last_signal_id: str = "0-0"
        self.last_ml_features_id: str = "$"
        self.prev_guard_states: dict[str, str] = {}
        self.adverse_model: Any | None = None
        self.adverse_model_path: str = ""
        self.adverse_model_loaded: bool = False
        self.sync_state_published_keys: set[str] = set()
        self.paper_exchange_mode_warned_instances: set[str] = set()
        self.paper_exchange_auto_mode_by_instance: dict[str, str] = {}
        self.paper_exchange_auto_mode_updated_ms_by_instance: dict[str, int] = {}
        self.last_paper_exchange_event_id: str = "0-0"
        self.paper_exchange_seen_event_ids: set[str] = set()
        self.paper_exchange_cursor_initialized: bool = False
        self.sync_requested_at_ms_by_key: dict[str, int] = {}
        self.sync_confirmed_keys: set[str] = set()
        self.sync_timeout_hard_stop_keys: set[str] = set()
        self.active_failure_streak_by_key: dict[str, int] = {}
        self.active_submit_order_cache: dict[str, tuple[str, float]] = {}
        self.active_cancel_command_cache: dict[str, tuple[str, float]] = {}
        self.active_cancel_all_command_cache: dict[str, tuple[str, float]] = {}

    def get_redis(self) -> Any | None:
        """Lazy-init a Redis client for signal consumption. Returns None when unavailable."""
        if self.redis_init_done:
            return self.redis_client
        _assert_owner_thread("BridgeState.get_redis")
        self.redis_init_done = True
        try:
            import redis as _redis_lib

            host = os.environ.get("REDIS_HOST", "")
            if not host:
                return None
            self.redis_client = _redis_lib.Redis(
                host=host,
                port=int(os.environ.get("REDIS_PORT", "6379")),
                db=int(os.environ.get("REDIS_DB", "0")),
                password=os.environ.get("REDIS_PASSWORD") or None,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                socket_keepalive=True,
            )
            logger.info("Signal consumer Redis client initialized (%s)", host)
            return self.redis_client
        except Exception as exc:
            logger.warning("Signal consumer Redis init failed: %s", exc)
            return None

    def _close_redis(self) -> None:
        """Close existing Redis client and its connection pool if present."""
        client = getattr(self, "redis_client", None)
        if client is None:
            return
        try:
            pool = getattr(client, "connection_pool", None)
            client.close()
            if pool is not None:
                pool.disconnect()
        except Exception:
            pass  # best-effort on shutdown


_bridge_state = BridgeState()

_LATENCY_TRACKER = JsonLatencyTracker(
    Path(
        os.getenv(
            "HB_BRIDGE_LATENCY_REPORT_PATH",
            "/workspace/hbot/reports/verification/hb_bridge_hot_path_latest.json",
        )
    ),
    max_samples=int(os.getenv("HB_BRIDGE_LATENCY_MAX_SAMPLES", "720")),
    flush_interval_s=float(os.getenv("HB_BRIDGE_LATENCY_FLUSH_S", "5")),
)


def _get_signal_redis() -> Any | None:
    """Lazy-init a Redis client for signal consumption. Returns None when unavailable."""
    return _bridge_state.get_redis()
