from __future__ import annotations

import os
from typing import List

from services.common.market_history_types import HistoryPolicy, MarketHistoryStatus

_KNOWN_SOURCES = {"quote_mid", "exchange_ohlcv"}


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        return int(raw)
    except Exception:
        return default


def _normalize_sources(raw: str) -> List[str]:
    out: List[str] = []
    for item in str(raw or "").split(","):
        source = str(item).strip().lower()
        if source in _KNOWN_SOURCES and source not in out:
            out.append(source)
    return out or ["quote_mid"]


def runtime_seed_policy(default_min_bars: int = 30) -> HistoryPolicy:
    preferred_sources = _normalize_sources(os.getenv("HB_HISTORY_SOURCE_PRIORITY", "quote_mid,exchange_ohlcv"))
    allow_fallback = _env_bool("HB_HISTORY_ALLOW_FALLBACK", False)
    min_status_raw = str(os.getenv("HB_HISTORY_RUNTIME_MIN_STATUS", "degraded")).strip().lower()
    min_status = "fresh" if min_status_raw == "fresh" else "degraded"
    return HistoryPolicy(
        preferred_sources=preferred_sources,
        allow_fallback=allow_fallback,
        require_closed=_env_bool("HB_HISTORY_REQUIRE_CLOSED", True),
        min_acceptable_status=min_status,
        min_bars_before_trading=max(1, _env_int("HB_HISTORY_RUNTIME_MIN_BARS", int(default_min_bars))),
        max_acceptable_gap_s=max(0, _env_int("HB_HISTORY_MAX_ACCEPTABLE_GAP_S", 300)),
    )


def status_meets_policy(status: MarketHistoryStatus, policy: HistoryPolicy) -> bool:
    bars_returned = int(status.bars_returned or 0)
    if bars_returned < max(0, int(policy.min_bars_before_trading)):
        return False
    if int(status.max_gap_s or 0) > max(0, int(policy.max_acceptable_gap_s)):
        return False
    allowed_statuses = {"fresh"} if policy.min_acceptable_status == "fresh" else {"fresh", "degraded", "stale"}
    return str(status.status or "empty") in allowed_statuses
