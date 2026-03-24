from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _connect() -> psycopg.Connection[Any]:
    if psycopg is None:
        raise RuntimeError("psycopg_not_installed")
    return psycopg.connect(
        host=os.getenv("OPS_DB_HOST", "postgres"),
        port=int(os.getenv("OPS_DB_PORT", "5432")),
        dbname=os.getenv("OPS_DB_NAME", "kzay_capital_ops"),
        user=os.getenv("OPS_DB_USER", "hbot"),
        password=os.getenv("OPS_DB_PASSWORD", "kzay_capital_dev_password"),
    )


def _apply_schema(conn: psycopg.Connection[Any], root: Path) -> None:
    schema_path = root / "services" / "ops_db_writer" / "schema_v2_market_bar.sql"
    with conn.cursor() as cur:
        cur.execute(schema_path.read_text(encoding="utf-8"))
    conn.commit()


def _where_clause(connector_name: str, trading_pair: str) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if connector_name:
        clauses.append("legacy.connector_name = %(connector_name)s")
        params["connector_name"] = connector_name
    if trading_pair:
        clauses.append("legacy.trading_pair = %(trading_pair)s")
        params["trading_pair"] = trading_pair
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _fetch_scalar(cur: psycopg.Cursor[Any], sql: str, params: dict[str, Any]) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def _sample_parity(cur: psycopg.Cursor[Any], where_sql: str, params: dict[str, Any], sample_limit: int) -> list[dict[str, Any]]:
    sample_sql = f"""
    SELECT
      legacy.bucket_minute_utc,
      legacy.connector_name,
      legacy.trading_pair,
      legacy.open_price,
      legacy.high_price,
      legacy.low_price,
      legacy.close_price,
      v2.open_price,
      v2.high_price,
      v2.low_price,
      v2.close_price
    FROM market_quote_bar_minute legacy
    JOIN market_bar_v2 v2
      ON v2.bucket_minute_utc = legacy.bucket_minute_utc
     AND v2.connector_name = legacy.connector_name
     AND v2.trading_pair = legacy.trading_pair
     AND v2.bar_source = 'quote_mid'
     AND v2.bar_interval_s = 60
    {where_sql}
    ORDER BY legacy.bucket_minute_utc DESC
    LIMIT %(sample_limit)s
    """
    cur.execute(sample_sql, {**params, "sample_limit": max(1, int(sample_limit))})
    rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for row in rows:
        legacy_vals = [float(row[3]), float(row[4]), float(row[5]), float(row[6])]
        v2_vals = [float(row[7]), float(row[8]), float(row[9]), float(row[10])]
        max_abs_diff = max(abs(a - b) for a, b in zip(legacy_vals, v2_vals, strict=True))
        out.append(
            {
                "bucket_minute_utc": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                "connector_name": str(row[1]),
                "trading_pair": str(row[2]),
                "max_abs_diff": max_abs_diff,
                "match": max_abs_diff <= 1e-9,
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill legacy quote-minute bars into market_bar_v2 and emit parity evidence.")
    parser.add_argument("--connector-name", default="", help="Optional connector filter.")
    parser.add_argument("--trading-pair", default="", help="Optional trading pair filter.")
    parser.add_argument("--sample-limit", type=int, default=25, help="Number of joined rows to sample for parity evidence.")
    parser.add_argument("--dry-run", action="store_true", help="Compute counts/report without writing to market_bar_v2.")
    parser.add_argument(
        "--report-path",
        default="reports/ops/market_bar_v2_backfill_latest.json",
        help="Path relative to hbot root for the JSON report.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    report_path = Path(args.report_path)
    if not report_path.is_absolute():
        report_path = root / report_path

    result: dict[str, Any] = {
        "ts_utc": _utc_now(),
        "status": "pass",
        "dry_run": bool(args.dry_run),
        "connector_name": str(args.connector_name or ""),
        "trading_pair": str(args.trading_pair or ""),
        "report_path": str(report_path),
    }

    conn = _connect()
    try:
        _apply_schema(conn, root)
        where_sql, params = _where_clause(str(args.connector_name or "").strip(), str(args.trading_pair or "").strip())
        missing_where_sql = (where_sql + " AND " if where_sql else "WHERE ") + "v2.bucket_minute_utc IS NULL"
        legacy_count_sql = f"SELECT COUNT(*) FROM market_quote_bar_minute legacy {where_sql}"
        v2_count_sql = f"""
        SELECT COUNT(*)
        FROM market_bar_v2 v2
        WHERE v2.bar_source = 'quote_mid'
          AND v2.bar_interval_s = 60
          {"AND v2.connector_name = %(connector_name)s" if params.get("connector_name") else ""}
          {"AND v2.trading_pair = %(trading_pair)s" if params.get("trading_pair") else ""}
        """
        missing_count_sql = f"""
        SELECT COUNT(*)
        FROM market_quote_bar_minute legacy
        LEFT JOIN market_bar_v2 v2
          ON v2.bucket_minute_utc = legacy.bucket_minute_utc
         AND v2.connector_name = legacy.connector_name
         AND v2.trading_pair = legacy.trading_pair
         AND v2.bar_source = 'quote_mid'
         AND v2.bar_interval_s = 60
        {missing_where_sql}
        """

        with conn.cursor() as cur:
            legacy_count_before = _fetch_scalar(cur, legacy_count_sql, params)
            v2_count_before = _fetch_scalar(cur, v2_count_sql, params)
            missing_count_before = _fetch_scalar(cur, missing_count_sql, params)
            inserted_rows = 0
            if not args.dry_run:
                backfill_sql = f"""
                INSERT INTO market_bar_v2 (
                  bucket_minute_utc,
                  connector_name,
                  trading_pair,
                  bar_source,
                  bar_interval_s,
                  open_price,
                  high_price,
                  low_price,
                  close_price,
                  volume_base,
                  volume_quote,
                  event_count,
                  first_ts_utc,
                  last_ts_utc,
                  ingest_ts_utc,
                  schema_version,
                  quality_flags
                )
                SELECT
                  legacy.bucket_minute_utc,
                  legacy.connector_name,
                  legacy.trading_pair,
                  'quote_mid',
                  60,
                  legacy.open_price,
                  legacy.high_price,
                  legacy.low_price,
                  legacy.close_price,
                  NULL,
                  NULL,
                  legacy.event_count,
                  legacy.first_ts_utc,
                  legacy.last_ts_utc,
                  NOW(),
                  2,
                  '{{}}'::jsonb
                FROM market_quote_bar_minute legacy
                LEFT JOIN market_bar_v2 v2
                  ON v2.bucket_minute_utc = legacy.bucket_minute_utc
                 AND v2.connector_name = legacy.connector_name
                 AND v2.trading_pair = legacy.trading_pair
                 AND v2.bar_source = 'quote_mid'
                 AND v2.bar_interval_s = 60
                {missing_where_sql}
                """
                cur.execute(backfill_sql, params)
                inserted_rows = max(0, int(cur.rowcount or 0))
                conn.commit()

            legacy_count_after = _fetch_scalar(cur, legacy_count_sql, params)
            v2_count_after = _fetch_scalar(cur, v2_count_sql, params)
            missing_count_after = _fetch_scalar(cur, missing_count_sql, params)
            parity_samples = _sample_parity(cur, where_sql, params, args.sample_limit)

        mismatches = [row for row in parity_samples if not bool(row.get("match", False))]
        result.update(
            {
                "legacy_count_before": legacy_count_before,
                "legacy_count_after": legacy_count_after,
                "v2_count_before": v2_count_before,
                "v2_count_after": v2_count_after,
                "missing_count_before": missing_count_before,
                "missing_count_after": missing_count_after,
                "inserted_rows": inserted_rows,
                "sample_limit": int(args.sample_limit),
                "sampled_rows": len(parity_samples),
                "sample_mismatch_count": len(mismatches),
                "sample_matches": len(parity_samples) - len(mismatches),
                "parity_samples": parity_samples,
            }
        )
        if mismatches:
            result["status"] = "fail"
            result["reason"] = "sample_parity_mismatch"
    except Exception as exc:
        result["status"] = "fail"
        result["reason"] = str(exc)
        raise
    finally:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        conn.close()

    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
