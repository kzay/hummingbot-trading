from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from platform_lib.core.utils import (
    utc_now as _utc_now,
)

from services.ops_db_writer.parsers import (
    SCHEMA_VERSION,
    _EPOCH_TS_UTC,
    _canonical_ts_utc,
    _depth_metrics,
    _env_bool,
    _env_int,
    _epoch_ms_to_ts_utc,
    _extract_position_from_desk_snapshot,
    _fill_key,
    _floor_minute_utc,
    _iter_jsonl_rows,
    _next_minute_utc,
    _normalize_depth_levels,
    _normalize_pair,
    _parse_ts,
    _read_csv_rows,
    _read_jsonl_rows,
    _safe_bool,
    _source_abs,
    _stream_entry_id_to_ts_utc,
)
from services.ops_db_writer.schema import (
    _apply_schema,
    _apply_timescale,
    _connect,
)
from services.ops_db_writer.ingestors import (
    _ingest_accounting_snapshots,
    _ingest_bot_position_current,
    _ingest_daily,
    _ingest_event_envelope_raw,
    _ingest_exchange_snapshot,
    _ingest_fills,
    _ingest_market_depth_layers,
    _ingest_market_quote_layers,
    _ingest_minutes,
    _ingest_paper_exchange_open_orders,
    _ingest_promotion_gates,
    _ingest_single_report,
)

__all__ = [
    "SCHEMA_VERSION",
    "_EPOCH_TS_UTC",
    "_apply_schema",
    "_apply_timescale",
    "_canonical_ts_utc",
    "_connect",
    "_depth_metrics",
    "_env_bool",
    "_env_int",
    "_epoch_ms_to_ts_utc",
    "_extract_position_from_desk_snapshot",
    "_fill_key",
    "_floor_minute_utc",
    "_ingest_accounting_snapshots",
    "_ingest_bot_position_current",
    "_ingest_daily",
    "_ingest_event_envelope_raw",
    "_ingest_exchange_snapshot",
    "_ingest_fills",
    "_ingest_market_depth_layers",
    "_ingest_market_quote_layers",
    "_ingest_minutes",
    "_ingest_paper_exchange_open_orders",
    "_ingest_promotion_gates",
    "_ingest_single_report",
    "_iter_jsonl_rows",
    "_next_minute_utc",
    "_normalize_depth_levels",
    "_normalize_pair",
    "_parse_ts",
    "_read_csv_rows",
    "_read_jsonl_rows",
    "_safe_bool",
    "_source_abs",
    "_stream_entry_id_to_ts_utc",
    "main",
    "run_once",
]


def run_once(root: Path, data_root: Path, reports_root: Path, *, apply_schema: bool = True) -> dict[str, object]:
    ingest_ts_utc = _utc_now()
    result: dict[str, object] = {
        "ts_utc": ingest_ts_utc,
        "status": "pass",
        "counts": {},
        "errors": [],
    }
    conn = None
    try:
        conn = _connect()
        if apply_schema:
            _apply_schema(conn, root)
            result["timescale"] = _apply_timescale(conn)
            conn.commit()
        else:
            result["timescale"] = {
                "enabled": _env_bool("OPS_DB_TIMESCALE_ENABLED", True),
                "required": _env_bool("OPS_DB_TIMESCALE_REQUIRED", False),
                "schema_apply_skipped": True,
            }
        counts: dict[str, object] = {}
        counts["bot_snapshot_minute"] = _ingest_minutes(conn, data_root, ingest_ts_utc)
        counts["bot_daily"] = _ingest_daily(conn, data_root, ingest_ts_utc)
        counts["fills"] = _ingest_fills(conn, data_root, ingest_ts_utc)
        counts["event_envelope_raw"] = _ingest_event_envelope_raw(conn, reports_root, ingest_ts_utc)
        counts["market_depth"] = _ingest_market_depth_layers(conn, reports_root, ingest_ts_utc)
        counts["market_quote"] = _ingest_market_quote_layers(conn, reports_root, ingest_ts_utc)
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
        counts["paper_exchange_open_order_current"] = _ingest_paper_exchange_open_orders(conn, reports_root, ingest_ts_utc)
        counts["bot_position_current"] = _ingest_bot_position_current(conn, reports_root, ingest_ts_utc)
        conn.commit()
        result["counts"] = counts
    except Exception as exc:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass  # Justification: best-effort rollback after DB error — connection may be aborted
        result["status"] = "fail"
        result["errors"] = [str(exc)]
    finally:
        if conn:
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
    apply_schema_each_run = _env_bool("OPS_DB_APPLY_SCHEMA_EACH_RUN", False)
    reports_out = reports_root / "ops_db_writer"
    reports_out.mkdir(parents=True, exist_ok=True)

    def _persist(result: dict[str, object]) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_file = reports_out / f"ops_db_writer_{stamp}.json"
        out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        (reports_out / "latest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        logger = logging.getLogger("ops_db_writer")
        logger.info("status=%s", result.get("status"))
        logger.info("counts=%s", result.get("counts"))
        logger.info("evidence=%s", out_file)

    if args.once:
        _persist(run_once(root, data_root, reports_root, apply_schema=True))
        return

    schema_ready = False
    while True:
        apply_schema_now = apply_schema_each_run or (not schema_ready)
        result = run_once(root, data_root, reports_root, apply_schema=apply_schema_now)
        if result.get("status") == "pass" and apply_schema_now:
            schema_ready = True
        _persist(result)
        time.sleep(max(30, interval_sec))


if __name__ == "__main__":
    main()
