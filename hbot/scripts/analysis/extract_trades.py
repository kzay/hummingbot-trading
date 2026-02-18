from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


def _table_names(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return [r[0] for r in rows]


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    return [r[1] for r in rows]


def _pick_table(conn: sqlite3.Connection) -> Optional[str]:
    preferred = ["trade_fills", "trades", "fills", "orders"]
    tables = _table_names(conn)
    for p in preferred:
        if p in tables:
            return p
    # Fall back to first table that looks trade-like.
    for t in tables:
        cols = set(_table_columns(conn, t))
        if {"price", "amount"} & cols and ("side" in cols or "trade_type" in cols):
            return t
    return None


def _first_present(row: Dict[str, Any], candidates: List[str], default: Any = None) -> Any:
    for c in candidates:
        if c in row and row[c] is not None:
            return row[c]
    return default


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _as_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v)


def load_normalized_trades(db_path: str, strategy_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        table = _pick_table(conn)
        if not table:
            return []
        rows = conn.execute(f"SELECT * FROM '{table}'").fetchall()
        norm_rows: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            strategy = _as_str(_first_present(d, [
                "strategy", "strategy_name", "controller_name", "config_file_path", "trade_source"
            ]), "")
            if strategy_filter and strategy_filter.lower() not in strategy.lower():
                continue

            side = _as_str(_first_present(d, ["side", "trade_type", "position", "order_side"]), "").upper()
            if side in {"BUY", "BID", "LONG"}:
                side = "BUY"
            elif side in {"SELL", "ASK", "SHORT"}:
                side = "SELL"

            norm_rows.append({
                "ts": _as_float(_first_present(d, ["timestamp", "trade_timestamp", "created_at", "creation_timestamp"], 0.0)),
                "strategy": strategy,
                "connector": _as_str(_first_present(d, ["exchange", "connector_name", "market"], "")),
                "pair": _as_str(_first_present(d, ["trading_pair", "symbol", "market"], "")),
                "side": side,
                "price": _as_float(_first_present(d, ["price", "fill_price", "trade_price"], 0.0)),
                "amount": _as_float(_first_present(d, ["amount", "size", "filled_amount", "quantity"], 0.0)),
                "fee": _as_float(_first_present(d, ["fee_paid", "fee", "commission"], 0.0)),
                "realized_pnl": _as_float(_first_present(d, ["realized_pnl", "pnl"], 0.0)),
                "source_table": table,
            })
        norm_rows.sort(key=lambda x: x["ts"])
        return norm_rows
    finally:
        conn.close()


def write_csv(rows: List[Dict[str, Any]], output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ts", "strategy", "connector", "pair", "side", "price", "amount", "fee", "realized_pnl", "source_table"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract normalized trade rows from Hummingbot SQLite DB.")
    parser.add_argument("--db", required=True, help="Path to sqlite database")
    parser.add_argument("--strategy-filter", default=None, help="Filter rows by strategy string")
    parser.add_argument("--output", required=True, help="Output CSV path")
    args = parser.parse_args()

    rows = load_normalized_trades(args.db, args.strategy_filter)
    write_csv(rows, args.output)
    print(f"Extracted {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
