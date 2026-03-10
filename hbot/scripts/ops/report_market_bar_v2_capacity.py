from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> "psycopg.Connection[Any]":
    if psycopg is None:
        raise RuntimeError("psycopg_not_installed")
    return psycopg.connect(
        host=os.getenv("OPS_DB_HOST", "postgres"),
        port=int(os.getenv("OPS_DB_PORT", "5432")),
        dbname=os.getenv("OPS_DB_NAME", "kzay_capital_ops"),
        user=os.getenv("OPS_DB_USER", "hbot"),
        password=os.getenv("OPS_DB_PASSWORD", "kzay_capital_dev_password"),
    )


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        return int(raw)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        return float(raw)
    except Exception:
        return default


def _dt_to_iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or "")


def _bytes_to_mb(value: float) -> float:
    return round(float(value) / (1024.0 * 1024.0), 3)


def _summarize_capacity(
    key_rows: List[Dict[str, Any]],
    *,
    retention_max_bars: int,
    max_distinct_keys: int,
    storage_budget_mb: float,
    total_table_bytes: int,
    total_index_bytes: int,
) -> Dict[str, Any]:
    distinct_keys = len(key_rows)
    total_rows = sum(int(row.get("row_count", 0) or 0) for row in key_rows)
    total_storage_bytes = float(total_table_bytes + total_index_bytes)
    bytes_per_row = (total_storage_bytes / float(total_rows)) if total_rows > 0 else 0.0
    per_key: List[Dict[str, Any]] = []
    over_cap_keys: List[str] = []
    near_cap_keys: List[str] = []
    max_utilization = 0.0

    for row in key_rows:
        row_count = int(row.get("row_count", 0) or 0)
        span_days = max(float(row.get("span_days", 0.0) or 0.0), 0.0)
        rows_per_day = (float(row_count) / span_days) if span_days > 0 else 0.0
        utilization_ratio = (float(row_count) / float(retention_max_bars)) if retention_max_bars > 0 else 0.0
        max_utilization = max(max_utilization, utilization_ratio)
        key_name = (
            f"{row.get('connector_name', '')}|{row.get('trading_pair', '')}|"
            f"{row.get('bar_source', '')}|{row.get('bar_interval_s', 0)}"
        )
        if utilization_ratio > 1.0:
            over_cap_keys.append(key_name)
        elif utilization_ratio >= 0.8:
            near_cap_keys.append(key_name)
        remaining_bars = max(0, int(retention_max_bars) - row_count)
        projected_days_to_cap = (float(remaining_bars) / rows_per_day) if rows_per_day > 0 else None
        per_key.append(
            {
                "connector_name": str(row.get("connector_name", "")),
                "trading_pair": str(row.get("trading_pair", "")),
                "bar_source": str(row.get("bar_source", "")),
                "bar_interval_s": int(row.get("bar_interval_s", 0) or 0),
                "row_count": row_count,
                "utilization_ratio": round(utilization_ratio, 6),
                "oldest_bucket_utc": str(row.get("oldest_bucket_utc", "")),
                "newest_bucket_utc": str(row.get("newest_bucket_utc", "")),
                "span_days": round(span_days, 6),
                "rows_per_day": round(rows_per_day, 3),
                "projected_days_to_cap": round(projected_days_to_cap, 3) if projected_days_to_cap is not None else None,
            }
        )

    per_key.sort(key=lambda item: (-float(item.get("utilization_ratio", 0.0)), -int(item.get("row_count", 0))))
    projected_capacity_rows = int(retention_max_bars) * max(0, distinct_keys)
    projected_capacity_total_mb = _bytes_to_mb(bytes_per_row * float(projected_capacity_rows))
    total_storage_mb = _bytes_to_mb(total_storage_bytes)

    status = "pass"
    reasons: List[str] = []
    if distinct_keys > int(max_distinct_keys):
        status = "fail"
        reasons.append("distinct_keys_above_budget")
    if over_cap_keys:
        status = "fail"
        reasons.append("retention_cap_exceeded")
    if total_storage_mb > float(storage_budget_mb):
        status = "warn" if status == "pass" else status
        reasons.append("storage_budget_exceeded")
    if near_cap_keys and status == "pass":
        status = "warn"
        reasons.append("retention_near_cap")

    return {
        "status": status,
        "reason": ",".join(reasons) if reasons else "",
        "retention_max_bars": int(retention_max_bars),
        "max_distinct_keys": int(max_distinct_keys),
        "storage_budget_mb": float(storage_budget_mb),
        "distinct_keys": distinct_keys,
        "total_rows": total_rows,
        "total_table_mb": _bytes_to_mb(float(total_table_bytes)),
        "total_index_mb": _bytes_to_mb(float(total_index_bytes)),
        "total_storage_mb": total_storage_mb,
        "bytes_per_row": round(bytes_per_row, 3),
        "projected_capacity_rows": projected_capacity_rows,
        "projected_capacity_total_mb": projected_capacity_total_mb,
        "max_utilization_ratio": round(max_utilization, 6),
        "over_cap_keys": over_cap_keys[:50],
        "near_cap_keys": near_cap_keys[:50],
        "keys": per_key[:200],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate capacity and retention evidence for market_bar_v2.")
    parser.add_argument(
        "--report-path",
        default="reports/ops/market_bar_v2_capacity_latest.json",
        help="Path relative to hbot root for the JSON report.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    report_path = Path(args.report_path)
    if not report_path.is_absolute():
        report_path = root / report_path

    retention_max_bars = max(1000, _env_int("OPS_DB_MARKET_BAR_V2_RETENTION_MAX_BARS", 100_000))
    max_distinct_keys = max(1, _env_int("OPS_DB_MARKET_BAR_V2_MAX_DISTINCT_KEYS", 50))
    storage_budget_mb = max(1.0, _env_float("OPS_DB_MARKET_BAR_V2_STORAGE_BUDGET_MB", 512.0))

    payload: Dict[str, Any] = {
        "ts_utc": _utc_now(),
        "report_path": str(report_path),
    }

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  connector_name,
                  trading_pair,
                  bar_source,
                  bar_interval_s,
                  COUNT(*) AS row_count,
                  MIN(bucket_minute_utc) AS oldest_bucket_utc,
                  MAX(bucket_minute_utc) AS newest_bucket_utc,
                  GREATEST(EXTRACT(EPOCH FROM (MAX(bucket_minute_utc) - MIN(bucket_minute_utc))) / 86400.0, 0.0) AS span_days
                FROM market_bar_v2
                GROUP BY connector_name, trading_pair, bar_source, bar_interval_s
                ORDER BY connector_name, trading_pair, bar_source, bar_interval_s
                """
            )
            key_rows = [
                {
                    "connector_name": str(row[0]),
                    "trading_pair": str(row[1]),
                    "bar_source": str(row[2]),
                    "bar_interval_s": int(row[3] or 0),
                    "row_count": int(row[4] or 0),
                    "oldest_bucket_utc": _dt_to_iso(row[5]),
                    "newest_bucket_utc": _dt_to_iso(row[6]),
                    "span_days": float(row[7] or 0.0),
                }
                for row in (cur.fetchall() or [])
            ]
            cur.execute(
                """
                SELECT
                  COALESCE(pg_relation_size('market_bar_v2'), 0),
                  COALESCE(pg_indexes_size('market_bar_v2'), 0)
                """
            )
            size_row = cur.fetchone() or (0, 0)
            total_table_bytes = int(size_row[0] or 0)
            total_index_bytes = int(size_row[1] or 0)

        payload.update(
            _summarize_capacity(
                key_rows,
                retention_max_bars=retention_max_bars,
                max_distinct_keys=max_distinct_keys,
                storage_budget_mb=storage_budget_mb,
                total_table_bytes=total_table_bytes,
                total_index_bytes=total_index_bytes,
            )
        )
    except Exception as exc:
        payload["status"] = "fail"
        payload["reason"] = str(exc)
        raise
    finally:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        conn.close()

    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") in {"pass", "warn"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
