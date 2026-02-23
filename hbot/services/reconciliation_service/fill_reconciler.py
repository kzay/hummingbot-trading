"""Exchange-side fill reconciliation.

Compares local fills (from ``fills.csv``) against exchange-reported trades
(via ccxt ``fetch_my_trades``) and flags discrepancies.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    import ccxt  # type: ignore
except Exception:
    ccxt = None

from services.common.utils import safe_float, utc_now, write_json

logger = logging.getLogger(__name__)


def _load_local_fills(fills_path: Path) -> List[Dict[str, str]]:
    """Read all rows from a fills CSV."""
    if not fills_path.exists():
        return []
    try:
        with fills_path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        logger.warning("Failed to read fills CSV: %s", fills_path, exc_info=True)
        return []


def _fetch_exchange_fills(
    exchange_id: str,
    api_key: str,
    secret: str,
    passphrase: str,
    symbol: str,
    since_ms: Optional[int] = None,
    limit: int = 200,
) -> Tuple[List[Dict], str]:
    """Fetch recent trades from the exchange via ccxt.

    Returns ``(trades, error_string)``.
    """
    if ccxt is None:
        return [], "ccxt_not_installed"
    exchange_cls = getattr(ccxt, exchange_id, None)
    if exchange_cls is None:
        return [], f"unknown_exchange_{exchange_id}"
    if not api_key or not secret:
        return [], "missing_credentials"

    try:
        cfg: Dict = {"apiKey": api_key, "secret": secret, "enableRateLimit": True}
        if passphrase:
            cfg["password"] = passphrase
        exchange = exchange_cls(cfg)
        trades = exchange.fetch_my_trades(symbol=symbol, since=since_ms, limit=limit)
        return trades, ""
    except Exception as exc:
        logger.error("fetch_my_trades failed on %s: %s", exchange_id, exc, exc_info=True)
        return [], str(exc)


def reconcile_fills(
    local_fills: List[Dict[str, str]],
    exchange_fills: List[Dict],
    price_tolerance_pct: float = 0.01,
    amount_tolerance_pct: float = 0.01,
) -> Dict[str, object]:
    """Compare local fills against exchange fills.

    Returns a report dict with:
    - ``missing_local``: fills on exchange not in local CSV
    - ``missing_exchange``: fills in local CSV not on exchange
    - ``price_mismatch``: fills where price differs beyond tolerance
    """
    local_order_ids: Set[str] = set()
    local_by_order: Dict[str, Dict] = {}
    for row in local_fills:
        oid = str(row.get("order_id", "")).strip()
        if oid:
            local_order_ids.add(oid)
            local_by_order[oid] = row

    exchange_order_ids: Set[str] = set()
    exchange_by_order: Dict[str, Dict] = {}
    for trade in exchange_fills:
        oid = str(trade.get("order", trade.get("orderId", ""))).strip()
        if oid:
            exchange_order_ids.add(oid)
            exchange_by_order[oid] = trade

    missing_local = sorted(exchange_order_ids - local_order_ids)
    missing_exchange = sorted(local_order_ids - exchange_order_ids)

    price_mismatches: List[Dict[str, object]] = []
    for oid in local_order_ids & exchange_order_ids:
        local_price = safe_float(local_by_order[oid].get("price"))
        exchange_price = safe_float(exchange_by_order[oid].get("price"))
        if local_price > 0 and exchange_price > 0:
            drift = abs(local_price - exchange_price) / exchange_price
            if drift > price_tolerance_pct:
                price_mismatches.append({
                    "order_id": oid,
                    "local_price": local_price,
                    "exchange_price": exchange_price,
                    "drift_pct": drift,
                })

    return {
        "matched_count": len(local_order_ids & exchange_order_ids),
        "missing_local_count": len(missing_local),
        "missing_exchange_count": len(missing_exchange),
        "price_mismatch_count": len(price_mismatches),
        "missing_local": missing_local[:20],
        "missing_exchange": missing_exchange[:20],
        "price_mismatches": price_mismatches[:10],
    }


def run_fill_reconciliation(
    data_root: Path,
    report_out: Path,
    exchange_id: str = "bitget",
    api_key: str = "",
    secret: str = "",
    passphrase: str = "",
    lookback_hours: int = 24,
) -> Dict[str, object]:
    """Run fill reconciliation for all bots that have fills.csv files."""
    since_ms = int((time.time() - lookback_hours * 3600) * 1000)
    bot_reports: List[Dict[str, object]] = []

    for fills_file in data_root.glob("*/logs/epp_v24/*/fills.csv"):
        bot = fills_file.parts[-5]
        local_fills = _load_local_fills(fills_file)
        if not local_fills:
            continue

        trading_pair = str(local_fills[0].get("trading_pair", "")).strip()
        if not trading_pair:
            continue
        symbol = trading_pair.replace("-", "/")

        exchange_fills, error = _fetch_exchange_fills(
            exchange_id=exchange_id,
            api_key=api_key,
            secret=secret,
            passphrase=passphrase,
            symbol=symbol,
            since_ms=since_ms,
        )

        if error:
            bot_reports.append({
                "bot": bot,
                "trading_pair": trading_pair,
                "status": "error",
                "error": error,
                "local_fill_count": len(local_fills),
            })
            continue

        recon = reconcile_fills(local_fills, exchange_fills)
        status = "ok"
        if recon["missing_local_count"] > 0 or recon["missing_exchange_count"] > 0:
            status = "warning"
        if recon["price_mismatch_count"] > 0:
            status = "critical"

        bot_reports.append({
            "bot": bot,
            "trading_pair": trading_pair,
            "status": status,
            "local_fill_count": len(local_fills),
            "exchange_fill_count": len(exchange_fills),
            **recon,
        })

    overall_status = "ok"
    if any(r.get("status") == "critical" for r in bot_reports):
        overall_status = "critical"
    elif any(r.get("status") in ("warning", "error") for r in bot_reports):
        overall_status = "warning"

    report = {
        "ts_utc": utc_now(),
        "status": overall_status,
        "exchange": exchange_id,
        "lookback_hours": lookback_hours,
        "bots": bot_reports,
    }
    write_json(report_out, report)
    return report
