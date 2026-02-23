from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

import psycopg


SCHEMA_VERSION = 1


from services.common.utils import (
    read_json as _read_json,
    safe_float as _safe_float,
    utc_now as _utc_now,
)


def _read_csv_rows(path: Path) -> Iterable[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as fp:
            return list(csv.DictReader(fp))
    except Exception:
        return []


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _source_abs(path: Path) -> str:
    return str(path.resolve())


def _fill_key(source_path: str, line_idx: int, row: Dict[str, str]) -> str:
    raw = "|".join(
        [
            source_path,
            str(line_idx),
            str(row.get("ts", "")),
            str(row.get("order_id", "")),
            str(row.get("trade_id", "")),
            str(row.get("side", "")),
            str(row.get("price", "")),
            str(row.get("amount", "")),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _connect() -> psycopg.Connection:
    host = os.getenv("OPS_DB_HOST", "postgres")
    port = int(os.getenv("OPS_DB_PORT", "5432"))
    dbname = os.getenv("OPS_DB_NAME", "hbot_ops")
    user = os.getenv("OPS_DB_USER", "hbot")
    password = os.getenv("OPS_DB_PASSWORD", "hbot_dev_password")
    return psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password)


def _apply_schema(conn: psycopg.Connection, root: Path) -> None:
    schema_path = root / "services" / "ops_db_writer" / "schema_v1.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _ingest_minutes(conn: psycopg.Connection, data_root: Path, ingest_ts_utc: str) -> int:
    inserted = 0
    sql = """
    INSERT INTO bot_snapshot_minute (
      bot, variant, ts_utc, exchange, trading_pair, state, regime, equity_quote, base_pct,
      target_base_pct, daily_loss_pct, drawdown_pct, cancel_per_min, orders_active, fills_count_today,
      fees_paid_today_quote, risk_reasons, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(bot)s, %(variant)s, %(ts_utc)s, %(exchange)s, %(trading_pair)s, %(state)s, %(regime)s, %(equity_quote)s,
      %(base_pct)s, %(target_base_pct)s, %(daily_loss_pct)s, %(drawdown_pct)s, %(cancel_per_min)s, %(orders_active)s,
      %(fills_count_today)s, %(fees_paid_today_quote)s, %(risk_reasons)s, %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (bot, variant, ts_utc) DO UPDATE SET
      exchange = EXCLUDED.exchange,
      trading_pair = EXCLUDED.trading_pair,
      state = EXCLUDED.state,
      regime = EXCLUDED.regime,
      equity_quote = EXCLUDED.equity_quote,
      base_pct = EXCLUDED.base_pct,
      target_base_pct = EXCLUDED.target_base_pct,
      daily_loss_pct = EXCLUDED.daily_loss_pct,
      drawdown_pct = EXCLUDED.drawdown_pct,
      cancel_per_min = EXCLUDED.cancel_per_min,
      orders_active = EXCLUDED.orders_active,
      fills_count_today = EXCLUDED.fills_count_today,
      fees_paid_today_quote = EXCLUDED.fees_paid_today_quote,
      risk_reasons = EXCLUDED.risk_reasons,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    with conn.cursor() as cur:
        for minute_file in data_root.glob("*/logs/epp_v24/*/minute.csv"):
            try:
                bot = minute_file.parts[-5]
                variant = minute_file.parts[-2]
            except Exception:
                continue
            source_path = _source_abs(minute_file)
            for row in _read_csv_rows(minute_file):
                ts = str(row.get("ts", "")).strip()
                if not ts:
                    continue
                payload = {
                    "bot": bot,
                    "variant": variant,
                    "ts_utc": ts,
                    "exchange": str(row.get("exchange", "")),
                    "trading_pair": str(row.get("trading_pair", "")),
                    "state": str(row.get("state", "")),
                    "regime": str(row.get("regime", "")),
                    "equity_quote": _safe_float(row.get("equity_quote")),
                    "base_pct": _safe_float(row.get("base_pct")),
                    "target_base_pct": _safe_float(row.get("target_base_pct")),
                    "daily_loss_pct": _safe_float(row.get("daily_loss_pct")),
                    "drawdown_pct": _safe_float(row.get("drawdown_pct")),
                    "cancel_per_min": _safe_float(row.get("cancel_per_min")),
                    "orders_active": _safe_float(row.get("orders_active")),
                    "fills_count_today": _safe_float(row.get("fills_count_today")),
                    "fees_paid_today_quote": _safe_float(row.get("fees_paid_today_quote")),
                    "risk_reasons": str(row.get("risk_reasons", "")),
                    "source_path": source_path,
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                }
                cur.execute(sql, payload)
                inserted += 1
    return inserted


def _ingest_daily(conn: psycopg.Connection, data_root: Path, ingest_ts_utc: str) -> int:
    inserted = 0
    sql = """
    INSERT INTO bot_daily (
      bot, variant, day_utc, ts_utc, exchange, trading_pair, state, equity_open_quote, equity_now_quote,
      pnl_quote, pnl_pct, turnover_x, fills_count, ops_events, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(bot)s, %(variant)s, %(day_utc)s, %(ts_utc)s, %(exchange)s, %(trading_pair)s, %(state)s, %(equity_open_quote)s,
      %(equity_now_quote)s, %(pnl_quote)s, %(pnl_pct)s, %(turnover_x)s, %(fills_count)s, %(ops_events)s, %(source_path)s,
      %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (bot, variant, day_utc) DO UPDATE SET
      ts_utc = EXCLUDED.ts_utc,
      exchange = EXCLUDED.exchange,
      trading_pair = EXCLUDED.trading_pair,
      state = EXCLUDED.state,
      equity_open_quote = EXCLUDED.equity_open_quote,
      equity_now_quote = EXCLUDED.equity_now_quote,
      pnl_quote = EXCLUDED.pnl_quote,
      pnl_pct = EXCLUDED.pnl_pct,
      turnover_x = EXCLUDED.turnover_x,
      fills_count = EXCLUDED.fills_count,
      ops_events = EXCLUDED.ops_events,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    with conn.cursor() as cur:
        for daily_file in data_root.glob("*/logs/epp_v24/*/daily.csv"):
            try:
                bot = daily_file.parts[-5]
                variant = daily_file.parts[-2]
            except Exception:
                continue
            source_path = _source_abs(daily_file)
            for row in _read_csv_rows(daily_file):
                ts = str(row.get("ts", "")).strip()
                dt = _parse_ts(ts)
                if dt is None:
                    continue
                payload = {
                    "bot": bot,
                    "variant": variant,
                    "day_utc": dt.date().isoformat(),
                    "ts_utc": ts,
                    "exchange": str(row.get("exchange", "")),
                    "trading_pair": str(row.get("trading_pair", "")),
                    "state": str(row.get("state", "")),
                    "equity_open_quote": _safe_float(row.get("equity_open_quote")),
                    "equity_now_quote": _safe_float(row.get("equity_now_quote")),
                    "pnl_quote": _safe_float(row.get("pnl_quote")),
                    "pnl_pct": _safe_float(row.get("pnl_pct")),
                    "turnover_x": _safe_float(row.get("turnover_x")),
                    "fills_count": _safe_float(row.get("fills_count")),
                    "ops_events": str(row.get("ops_events", "")),
                    "source_path": source_path,
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                }
                cur.execute(sql, payload)
                inserted += 1
    return inserted


def _ingest_fills(conn: psycopg.Connection, data_root: Path, ingest_ts_utc: str) -> int:
    inserted = 0
    sql = """
    INSERT INTO fills (
      fill_key, bot, variant, ts_utc, trade_id, order_id, side, price, amount, fee_paid_quote,
      source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(fill_key)s, %(bot)s, %(variant)s, %(ts_utc)s, %(trade_id)s, %(order_id)s, %(side)s, %(price)s, %(amount)s, %(fee_paid_quote)s,
      %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (fill_key) DO UPDATE SET
      ts_utc = EXCLUDED.ts_utc,
      trade_id = EXCLUDED.trade_id,
      order_id = EXCLUDED.order_id,
      side = EXCLUDED.side,
      price = EXCLUDED.price,
      amount = EXCLUDED.amount,
      fee_paid_quote = EXCLUDED.fee_paid_quote,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    with conn.cursor() as cur:
        for fills_file in data_root.glob("*/logs/epp_v24/*/fills.csv"):
            try:
                bot = fills_file.parts[-5]
                variant = fills_file.parts[-2]
            except Exception:
                continue
            source_path = _source_abs(fills_file)
            rows = list(_read_csv_rows(fills_file))
            for idx, row in enumerate(rows, start=2):
                payload = {
                    "fill_key": _fill_key(source_path, idx, row),
                    "bot": bot,
                    "variant": variant,
                    "ts_utc": str(row.get("ts", "")).strip() or None,
                    "trade_id": str(row.get("trade_id", "")).strip() or None,
                    "order_id": str(row.get("order_id", "")).strip() or None,
                    "side": str(row.get("side", "")).strip() or None,
                    "price": _safe_float(row.get("price"), 0.0),
                    "amount": _safe_float(row.get("amount"), 0.0),
                    "fee_paid_quote": _safe_float(row.get("fee_paid_quote"), 0.0),
                    "source_path": source_path,
                    "ingest_ts_utc": ingest_ts_utc,
                    "schema_version": SCHEMA_VERSION,
                }
                cur.execute(sql, payload)
                inserted += 1
    return inserted


def _ingest_exchange_snapshot(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> int:
    path = reports_root / "exchange_snapshots" / "latest.json"
    payload = _read_json(path)
    ts = str(payload.get("ts_utc", "")).strip()
    bots = payload.get("bots", {})
    if not ts or not isinstance(bots, dict):
        return 0
    sql = """
    INSERT INTO exchange_snapshot (
      bot, ts_utc, exchange, trading_pair, source, equity_quote, base_pct, account_probe_status,
      payload, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(bot)s, %(ts_utc)s, %(exchange)s, %(trading_pair)s, %(source)s, %(equity_quote)s, %(base_pct)s, %(account_probe_status)s,
      %(payload)s::jsonb, %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (bot, ts_utc) DO UPDATE SET
      exchange = EXCLUDED.exchange,
      trading_pair = EXCLUDED.trading_pair,
      source = EXCLUDED.source,
      equity_quote = EXCLUDED.equity_quote,
      base_pct = EXCLUDED.base_pct,
      account_probe_status = EXCLUDED.account_probe_status,
      payload = EXCLUDED.payload,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    count = 0
    with conn.cursor() as cur:
        for bot, bot_data in bots.items():
            if not isinstance(bot_data, dict):
                continue
            row = {
                "bot": str(bot),
                "ts_utc": ts,
                "exchange": str(bot_data.get("exchange", "")),
                "trading_pair": str(bot_data.get("trading_pair", "")),
                "source": str(bot_data.get("source", "")),
                "equity_quote": _safe_float(bot_data.get("equity_quote"), 0.0),
                "base_pct": _safe_float(bot_data.get("base_pct"), 0.0),
                "account_probe_status": str(bot_data.get("account_probe_status", "unknown")),
                "payload": json.dumps(bot_data),
                "source_path": _source_abs(path),
                "ingest_ts_utc": ingest_ts_utc,
                "schema_version": SCHEMA_VERSION,
            }
            cur.execute(sql, row)
            count += 1
    return count


def _ingest_single_report(
    conn: psycopg.Connection,
    report_path: Path,
    table: str,
    mapped_fields: Dict[str, str],
    ingest_ts_utc: str,
) -> int:
    payload = _read_json(report_path)
    ts = str(payload.get("ts_utc", "")).strip()
    if not ts:
        return 0

    cols = ["ts_utc"] + list(mapped_fields.keys()) + ["payload", "source_path", "ingest_ts_utc", "schema_version"]
    values = {col: None for col in cols}
    values["ts_utc"] = ts
    for col, key in mapped_fields.items():
        values[col] = payload.get(key)
    values["payload"] = json.dumps(payload)
    values["source_path"] = _source_abs(report_path)
    values["ingest_ts_utc"] = ingest_ts_utc
    values["schema_version"] = SCHEMA_VERSION

    set_cols = [c for c in cols if c != "ts_utc"]
    sql = f"""
    INSERT INTO {table} ({", ".join(cols)})
    VALUES ({", ".join([f"%({c})s::jsonb" if c == "payload" else f"%({c})s" for c in cols])})
    ON CONFLICT (ts_utc) DO UPDATE SET
      {", ".join([f"{c}=EXCLUDED.{c}" for c in set_cols])}
    """
    with conn.cursor() as cur:
        cur.execute(sql, values)
    return 1


def _ingest_accounting_snapshots(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> int:
    recon_path = reports_root / "reconciliation" / "latest.json"
    recon = _read_json(recon_path)
    ts = str(recon.get("ts_utc", "")).strip()
    snapshots = recon.get("accounting_snapshots", [])
    if not ts or not isinstance(snapshots, list):
        return 0

    sql = """
    INSERT INTO accounting_snapshot (
      bot, ts_utc, exchange, trading_pair, mid, equity_quote, base_balance, quote_balance, fees_paid_today_quote,
      funding_paid_today_quote, daily_loss_pct, drawdown_pct, fee_source, payload, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(bot)s, %(ts_utc)s, %(exchange)s, %(trading_pair)s, %(mid)s, %(equity_quote)s, %(base_balance)s, %(quote_balance)s, %(fees_paid_today_quote)s,
      %(funding_paid_today_quote)s, %(daily_loss_pct)s, %(drawdown_pct)s, %(fee_source)s, %(payload)s::jsonb, %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (bot, ts_utc) DO UPDATE SET
      exchange = EXCLUDED.exchange,
      trading_pair = EXCLUDED.trading_pair,
      mid = EXCLUDED.mid,
      equity_quote = EXCLUDED.equity_quote,
      base_balance = EXCLUDED.base_balance,
      quote_balance = EXCLUDED.quote_balance,
      fees_paid_today_quote = EXCLUDED.fees_paid_today_quote,
      funding_paid_today_quote = EXCLUDED.funding_paid_today_quote,
      daily_loss_pct = EXCLUDED.daily_loss_pct,
      drawdown_pct = EXCLUDED.drawdown_pct,
      fee_source = EXCLUDED.fee_source,
      payload = EXCLUDED.payload,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    count = 0
    with conn.cursor() as cur:
        for row in snapshots:
            if not isinstance(row, dict):
                continue
            payload = {
                "bot": str(row.get("bot", "")).strip(),
                "ts_utc": ts,
                "exchange": str(row.get("exchange", "")).strip(),
                "trading_pair": str(row.get("trading_pair", "")).strip(),
                "mid": _safe_float(row.get("mid"), 0.0),
                "equity_quote": _safe_float(row.get("equity_quote"), 0.0),
                "base_balance": _safe_float(row.get("base_balance"), 0.0),
                "quote_balance": _safe_float(row.get("quote_balance"), 0.0),
                "fees_paid_today_quote": _safe_float(row.get("fees_paid_today_quote"), 0.0),
                "funding_paid_today_quote": _safe_float(row.get("funding_paid_today_quote"), 0.0),
                "daily_loss_pct": _safe_float(row.get("daily_loss_pct"), 0.0),
                "drawdown_pct": _safe_float(row.get("drawdown_pct"), 0.0),
                "fee_source": str(row.get("fee_source", "")).strip(),
                "payload": json.dumps(row),
                "source_path": _source_abs(recon_path),
                "ingest_ts_utc": ingest_ts_utc,
                "schema_version": SCHEMA_VERSION,
            }
            if not payload["bot"]:
                continue
            cur.execute(sql, payload)
            count += 1
    return count


def _ingest_promotion_gates(conn: psycopg.Connection, reports_root: Path, ingest_ts_utc: str) -> int:
    sql = """
    INSERT INTO promotion_gate_run (
      run_id, ts_utc, status, critical_failures, payload, source_path, ingest_ts_utc, schema_version
    )
    VALUES (
      %(run_id)s, %(ts_utc)s, %(status)s, %(critical_failures)s::jsonb, %(payload)s::jsonb, %(source_path)s, %(ingest_ts_utc)s, %(schema_version)s
    )
    ON CONFLICT (run_id) DO UPDATE SET
      ts_utc = EXCLUDED.ts_utc,
      status = EXCLUDED.status,
      critical_failures = EXCLUDED.critical_failures,
      payload = EXCLUDED.payload,
      source_path = EXCLUDED.source_path,
      ingest_ts_utc = EXCLUDED.ingest_ts_utc,
      schema_version = EXCLUDED.schema_version
    """
    count = 0
    with conn.cursor() as cur:
        for gate_file in sorted((reports_root / "promotion_gates").glob("promotion_gates_*.json")):
            payload = _read_json(gate_file)
            run_id = gate_file.stem
            row = {
                "run_id": run_id,
                "ts_utc": str(payload.get("ts_utc", "")).strip() or None,
                "status": str(payload.get("status", "")).strip() or None,
                "critical_failures": json.dumps(payload.get("critical_failures", [])),
                "payload": json.dumps(payload),
                "source_path": _source_abs(gate_file),
                "ingest_ts_utc": ingest_ts_utc,
                "schema_version": SCHEMA_VERSION,
            }
            cur.execute(sql, row)
            count += 1
    return count


def run_once(root: Path, data_root: Path, reports_root: Path) -> Dict[str, object]:
    ingest_ts_utc = _utc_now()
    result = {
        "ts_utc": ingest_ts_utc,
        "status": "pass",
        "counts": {},
        "errors": [],
    }
    conn = _connect()
    try:
        _apply_schema(conn, root)
        counts = {}
        counts["bot_snapshot_minute"] = _ingest_minutes(conn, data_root, ingest_ts_utc)
        counts["bot_daily"] = _ingest_daily(conn, data_root, ingest_ts_utc)
        counts["fills"] = _ingest_fills(conn, data_root, ingest_ts_utc)
        counts["exchange_snapshot"] = _ingest_exchange_snapshot(conn, reports_root, ingest_ts_utc)
        counts["reconciliation_report"] = _ingest_single_report(
            conn,
            reports_root / "reconciliation" / "latest.json",
            "reconciliation_report",
            {"status": "status", "critical_count": "critical_count", "warning_count": "warning_count"},
            ingest_ts_utc,
        )
        counts["accounting_snapshot"] = _ingest_accounting_snapshots(conn, reports_root, ingest_ts_utc)
        counts["parity_report"] = _ingest_single_report(
            conn,
            reports_root / "parity" / "latest.json",
            "parity_report",
            {"status": "status", "failed_bots": "failed_bots", "checked_bots": "checked_bots"},
            ingest_ts_utc,
        )
        counts["portfolio_risk_report"] = _ingest_single_report(
            conn,
            reports_root / "portfolio_risk" / "latest.json",
            "portfolio_risk_report",
            {
                "status": "status",
                "critical_count": "critical_count",
                "warning_count": "warning_count",
                "portfolio_action": "portfolio_action",
            },
            ingest_ts_utc,
        )
        counts["promotion_gate_run"] = _ingest_promotion_gates(conn, reports_root, ingest_ts_utc)
        conn.commit()
        result["counts"] = counts
    except Exception as exc:
        conn.rollback()
        result["status"] = "fail"
        result["errors"] = [str(exc)]
    finally:
        conn.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest CSV/JSON ops artifacts into Postgres.")
    parser.add_argument("--once", action="store_true", help="Run one ingestion cycle and exit.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    data_root = Path(os.getenv("HB_DATA_ROOT", str(root / "data")))
    reports_root = Path(os.getenv("HB_REPORTS_ROOT", str(root / "reports")))
    interval_sec = int(os.getenv("OPS_DB_WRITER_INTERVAL_SEC", "300"))
    reports_out = reports_root / "ops_db_writer"
    reports_out.mkdir(parents=True, exist_ok=True)

    def _persist(result: Dict[str, object]) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = reports_out / f"ops_db_writer_{stamp}.json"
        out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        (reports_out / "latest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"[ops-db-writer] status={result.get('status')}")
        print(f"[ops-db-writer] counts={result.get('counts')}")
        print(f"[ops-db-writer] evidence={out_file}")

    if args.once:
        _persist(run_once(root, data_root, reports_root))
        return

    while True:
        _persist(run_once(root, data_root, reports_root))
        time.sleep(max(30, interval_sec))


if __name__ == "__main__":
    main()
