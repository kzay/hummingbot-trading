"""Canonical desk snapshot service for INFRA-5.

Materializes a single authoritative snapshot per bot from multiple upstream
sources (minute.csv, fills.csv, open_orders_latest.json, daily_state,
reports/*.json) and writes it to:

    reports/desk_snapshot/<bot>/latest.json

Both the Telegram bot and Prometheus metrics exporter read this file as their
primary data source, falling back to raw files only when the snapshot is
missing or stale.

Schema version bumps are additive; consumers must tolerate unknown fields.

Run:
    python services/desk_snapshot_service/main.py
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.common.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SNAPSHOT_SCHEMA_VERSION = 1
STALE_MINUTES_WARN = 2.0          # snapshot warns if minute.csv older than this
REQUIRED_MINUTE_FIELDS = [
    "ts", "state", "regime", "equity_quote", "spread_pct", "net_edge_pct",
    "base_pct", "daily_loss_pct", "drawdown_pct", "orders_active",
    "realized_pnl_today_quote",
]
REQUIRED_SNAPSHOT_FIELDS = ["minute", "fill_stats", "gates"]

_DATA_ROOT = Path(os.environ.get("HB_DATA_ROOT", ""))
if not _DATA_ROOT or not _DATA_ROOT.is_absolute():
    _DATA_ROOT = Path(__file__).resolve().parents[2] / "data"

_REPORTS_ROOT = Path(os.environ.get("HB_REPORTS_ROOT", ""))
if not _REPORTS_ROOT or not _REPORTS_ROOT.is_absolute():
    _REPORTS_ROOT = Path(__file__).resolve().parents[2] / "reports"

_POLL_INTERVAL_S = float(os.environ.get("SNAPSHOT_POLL_INTERVAL_S", "30"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch_now() -> float:
    return time.time()


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _read_last_csv_row(path: Path) -> Optional[Dict[str, str]]:
    if not path.exists():
        return None
    try:
        last: Optional[Dict[str, str]] = None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                last = dict(row)
        return last
    except Exception as exc:
        logger.debug("Failed reading %s: %s", path, exc)
        return None


def _read_last_n_csv_rows(path: Path, n: int) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        rows: List[Dict[str, str]] = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
        return rows[-n:]
    except Exception:
        return []


def _read_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _read_daily_state(log_dir: Path) -> Optional[Dict]:
    """Try both daily state filenames used by the controller."""
    candidates = list(log_dir.glob("daily_state_*.json")) + [log_dir / "daily_state.json"]
    for p in sorted(candidates, reverse=True):
        d = _read_json(p)
        if d:
            return d
    return None


def _compute_fill_stats(fills_path: Path) -> Dict[str, Any]:
    """Summarize fills.csv into a compact dict."""
    stats: Dict[str, Any] = {
        "total": 0, "buys": 0, "sells": 0,
        "maker_total": 0, "taker_total": 0,
        "buy_notional": 0.0, "sell_notional": 0.0,
        "total_fees": 0.0, "total_realized_pnl": 0.0,
        "last_ts": "", "last_side": "", "last_price": 0.0, "last_amount": 0.0,
        "last_epoch": 0.0,
        "first_epoch": 0.0,
    }
    if not fills_path.exists():
        return stats
    try:
        with fills_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                side = str(row.get("side", "")).upper()
                price = _safe_float(row.get("price"))
                amount = _safe_float(row.get("amount_base"))
                fee = _safe_float(row.get("fee_quote", row.get("fee", 0)))
                pnl = _safe_float(row.get("realized_pnl_quote"))
                is_maker = str(row.get("is_maker", "")).lower() == "true"
                ts_str = str(row.get("ts", ""))
                notional = price * amount
                stats["total"] += 1
                if side == "BUY":
                    stats["buys"] += 1
                    stats["buy_notional"] += notional
                elif side == "SELL":
                    stats["sells"] += 1
                    stats["sell_notional"] += notional
                if is_maker:
                    stats["maker_total"] += 1
                else:
                    stats["taker_total"] += 1
                stats["total_fees"] += fee
                stats["total_realized_pnl"] += pnl
                # track first and last
                try:
                    epoch = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                    if stats["first_epoch"] == 0.0:
                        stats["first_epoch"] = epoch
                    stats["last_epoch"] = epoch
                    stats["last_ts"] = ts_str
                    stats["last_side"] = side
                    stats["last_price"] = price
                    stats["last_amount"] = amount
                except Exception:
                    pass
    except Exception as exc:
        logger.debug("fill_stats error %s: %s", fills_path, exc)
    return stats


def _read_open_orders(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    payload = _read_json(path)
    if not payload:
        return []
    orders = payload.get("orders", [])
    return orders if isinstance(orders, list) else []


def _read_portfolio(path: Path) -> Dict:
    d = _read_json(path)
    return d if isinstance(d, dict) else {}


def _read_gates() -> Dict[str, Any]:
    return {
        "promotion": _read_json(_REPORTS_ROOT / "promotion_gates" / "latest.json") or {},
        "strict_cycle": _read_json(_REPORTS_ROOT / "promotion_gates" / "strict_cycle_latest.json") or {},
        "day2": _read_json(_REPORTS_ROOT / "event_store" / "day2_gate_eval_latest.json") or {},
        "soak": _read_json(_REPORTS_ROOT / "paper_soak" / "latest.json") or {},
        "reconciliation": _read_json(_REPORTS_ROOT / "reconciliation" / "latest.json") or {},
    }


def _completeness(minute: Optional[Dict[str, str]]) -> Tuple[float, List[str]]:
    """Return (score 0-1, missing_fields list) based on required minute fields."""
    if not minute:
        return 0.0, list(REQUIRED_MINUTE_FIELDS)
    missing = [f for f in REQUIRED_MINUTE_FIELDS if not minute.get(f)]
    score = 1.0 - len(missing) / len(REQUIRED_MINUTE_FIELDS)
    return round(score, 3), missing


# ---------------------------------------------------------------------------
# Core snapshot builder
# ---------------------------------------------------------------------------

def build_snapshot(bot_name: str, bot_data_dir: Path) -> Dict[str, Any]:
    """Build a full canonical snapshot for one bot."""
    now_epoch = _epoch_now()
    log_dirs = sorted(bot_data_dir.glob("logs/epp_v24/*/"))

    minute_row: Optional[Dict[str, str]] = None
    fills_stats: Dict[str, Any] = {}
    open_orders: List[Dict] = []
    daily_state: Optional[Dict] = None
    portfolio: Dict = {}
    minute_age_s = float("inf")
    fill_age_s = float("inf")

    for log_dir in log_dirs:
        m = _read_last_csv_row(log_dir / "minute.csv")
        if m:
            minute_row = m
            # Compute minute age
            ts_str = str(m.get("ts", ""))
            try:
                epoch = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                minute_age_s = now_epoch - epoch
            except Exception:
                pass

        fs = _compute_fill_stats(log_dir / "fills.csv")
        if fs.get("total", 0) > fills_stats.get("total", 0):
            fills_stats = fs
            if fs["last_epoch"] > 0:
                fill_age_s = now_epoch - fs["last_epoch"]

        oo = _read_open_orders(bot_data_dir / "logs" / "recovery" / "open_orders_latest.json")
        if oo:
            open_orders = oo

        ds = _read_daily_state(log_dir)
        if ds:
            daily_state = ds

        pf = _read_portfolio(log_dir / "paper_desk_v2.json")
        if pf:
            portfolio = pf

    completeness_score, missing_fields = _completeness(minute_row)

    source_ts = str(minute_row.get("ts", "")) if minute_row else ""

    snapshot: Dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "bot": bot_name,
        "source_ts": source_ts,
        "generated_ts": _now_utc(),
        "minute_age_s": round(minute_age_s, 1) if minute_age_s != float("inf") else None,
        "fill_age_s": round(fill_age_s, 1) if fill_age_s != float("inf") else None,
        "completeness": completeness_score,
        "missing_fields": missing_fields,
        "minute": minute_row or {},
        "fill_stats": fills_stats,
        "daily_state": daily_state or {},
        "open_orders": open_orders,
        "portfolio": portfolio,
        "gates": _read_gates(),
    }
    return snapshot


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_snapshot(snapshot: Dict[str, Any]) -> Path:
    bot = snapshot["bot"]
    out_dir = _REPORTS_ROOT / "desk_snapshot" / bot
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest.json"
    tmp_path = out_dir / "latest.json.tmp"
    tmp_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)
    return out_path


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _discover_bots() -> List[Tuple[str, Path]]:
    bots: List[Tuple[str, Path]] = []
    try:
        for d in sorted(_DATA_ROOT.iterdir()):
            if d.is_dir() and (d / "logs").exists():
                bots.append((d.name, d))
    except OSError:
        pass
    return bots


def run_once() -> Dict[str, Any]:
    bots = _discover_bots()
    results: Dict[str, Any] = {}
    if not bots:
        logger.warning("No bot directories found under %s", _DATA_ROOT)
        return results
    for bot_name, bot_dir in bots:
        try:
            snap = build_snapshot(bot_name, bot_dir)
            path = write_snapshot(snap)
            results[bot_name] = {
                "ok": True,
                "completeness": snap["completeness"],
                "minute_age_s": snap["minute_age_s"],
                "fill_age_s": snap["fill_age_s"],
                "path": str(path),
            }
            logger.info(
                "snapshot %s: completeness=%.2f minute_age=%s fill_age=%s",
                bot_name,
                snap["completeness"],
                snap.get("minute_age_s"),
                snap.get("fill_age_s"),
            )
        except Exception as exc:
            logger.exception("Error building snapshot for %s: %s", bot_name, exc)
            results[bot_name] = {"ok": False, "error": str(exc)}
    return results


def main() -> None:
    logger.info(
        "desk_snapshot_service starting — data=%s reports=%s poll=%ss",
        _DATA_ROOT, _REPORTS_ROOT, _POLL_INTERVAL_S,
    )
    while True:
        try:
            run_once()
        except Exception as exc:
            logger.exception("Unexpected error in run_once: %s", exc)
        time.sleep(_POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
