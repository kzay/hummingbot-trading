from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from platform_lib.core.utils import (
    safe_float as _safe_float,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_EPOCH_TS_UTC = "1970-01-01T00:00:00+00:00"


def _read_csv_rows(path: Path) -> Iterator[dict[str, str]]:
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as fp:
            for row in csv.DictReader(fp):
                yield row
    except Exception:
        return


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _stream_entry_id_to_ts_utc(stream_entry_id: str) -> str | None:
    raw = str(stream_entry_id or "").strip()
    if not raw:
        return None
    ms_part = raw.split("-", 1)[0].strip()
    if not ms_part or not ms_part.lstrip("-").isdigit():
        return None
    try:
        return datetime.fromtimestamp(int(ms_part) / 1000.0, tz=UTC).isoformat()
    except Exception:
        return None


def _canonical_ts_utc(value: Any, default: str = _EPOCH_TS_UTC) -> str:
    parsed = _parse_ts(str(value or "").strip())
    if parsed is not None:
        return parsed.astimezone(UTC).isoformat()
    return default


def _floor_minute_utc(ts_utc: str) -> str:
    parsed = _parse_ts(ts_utc)
    if parsed is None:
        parsed = datetime.fromtimestamp(0, tz=UTC)
    floored = parsed.astimezone(UTC).replace(second=0, microsecond=0)
    return floored.isoformat()


def _next_minute_utc(ts_utc: str) -> str:
    parsed = _parse_ts(ts_utc)
    if parsed is None:
        parsed = datetime.fromtimestamp(0, tz=UTC)
    next_minute = parsed.astimezone(UTC) + timedelta(minutes=1)
    return next_minute.isoformat()


def _epoch_ms_to_ts_utc(value: Any, default: str = _EPOCH_TS_UTC) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        ms = int(float(raw))
    except Exception:
        return default
    if ms <= 0:
        return default
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat()
    except Exception:
        return default


def _normalize_depth_levels(raw_levels: Any, max_levels: int) -> list[dict[str, float]]:
    if not isinstance(raw_levels, list):
        return []
    out: list[dict[str, float]] = []
    for entry in raw_levels:
        price = None
        size = None
        if isinstance(entry, dict):
            price = _safe_float(entry.get("price"))
            size = _safe_float(entry.get("size", entry.get("amount", entry.get("quantity"))))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            price = _safe_float(entry[0])
            size = _safe_float(entry[1])
        if price is None or size is None:
            continue
        if price <= 0 or size <= 0:
            continue
        out.append({"price": float(price), "size": float(size)})
        if len(out) >= max_levels:
            break
    return out


def _depth_metrics(bids: list[dict[str, float]], asks: list[dict[str, float]]) -> dict[str, float | None]:
    best_bid = bids[0]["price"] if bids else None
    best_ask = asks[0]["price"] if asks else None
    mid_price = None
    spread_bps = None
    if best_bid is not None and best_ask is not None and best_ask >= best_bid:
        mid_price = (best_bid + best_ask) / 2.0
        if mid_price > 0:
            spread_bps = ((best_ask - best_bid) / mid_price) * 10_000.0
    bid_depth_total = float(sum(level["size"] for level in bids))
    ask_depth_total = float(sum(level["size"] for level in asks))
    denom = bid_depth_total + ask_depth_total
    imbalance = ((bid_depth_total - ask_depth_total) / denom) if denom > 0 else 0.0
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": mid_price,
        "spread_bps": spread_bps,
        "bid_depth_total": bid_depth_total,
        "ask_depth_total": ask_depth_total,
        "depth_imbalance": imbalance,
    }


def _read_jsonl_rows(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fp:
            for raw in fp:
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    yield payload
    except Exception:
        return


def _iter_jsonl_rows(path: Path, *, start_line: int = 1) -> Iterator[tuple[int, dict[str, Any]]]:
    if not path.exists():
        return
    start = max(1, int(start_line))
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fp:
            for line_idx, raw in enumerate(fp, start=1):
                if line_idx < start:
                    continue
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    yield line_idx, payload
    except Exception:
        return


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_pair(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "").replace("-", "").replace("_", "")


def _extract_position_from_desk_snapshot(snapshot: dict[str, Any], trading_pair: str) -> dict[str, Any]:
    pair_norm = _normalize_pair(trading_pair)
    portfolio = snapshot.get("portfolio")
    if isinstance(portfolio, dict):
        portfolio = portfolio.get("portfolio", portfolio)
    positions = portfolio.get("positions", {}) if isinstance(portfolio, dict) else {}
    if not isinstance(positions, dict):
        positions = {}
    for raw_key, raw_pos in positions.items():
        raw_pos = raw_pos if isinstance(raw_pos, dict) else {}
        key_norm = _normalize_pair(str(raw_key))
        pos_pair_norm = _normalize_pair(raw_pos.get("trading_pair", ""))
        if pair_norm and pair_norm not in {key_norm, pos_pair_norm}:
            continue
        return raw_pos
    return {}


def _source_abs(path: Path) -> str:
    return str(path.resolve())


def _fill_key(source_path: str, line_idx: int, row: dict[str, str]) -> str:
    raw = "|".join(
        [
            source_path,
            str(line_idx),
            str(row.get("ts", "")),
            str(row.get("order_id", "")),
            str(row.get("trade_id", "")),
            str(row.get("side", "")),
            str(row.get("price", "")),
            # Keep key derivation stable across writer versions for idempotent re-runs.
            str(row.get("amount", "")),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except Exception:
        return default
