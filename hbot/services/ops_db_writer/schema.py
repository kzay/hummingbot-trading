from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

try:
    import psycopg
except Exception:  # pragma: no cover - optional in lightweight test environments.
    psycopg = None  # type: ignore[assignment]

from services.ops_db_writer.parsers import _env_bool, _env_int

logger = logging.getLogger(__name__)


def _connect() -> psycopg.Connection:
    if psycopg is None:
        raise RuntimeError("psycopg_not_installed")
    host = os.getenv("OPS_DB_HOST", "postgres")
    port = int(os.getenv("OPS_DB_PORT", "5432"))
    dbname = os.getenv("OPS_DB_NAME", "kzay_capital_ops")
    user = os.getenv("OPS_DB_USER", "hbot")
    password = os.getenv("OPS_DB_PASSWORD", "kzay_capital_dev_password")
    return psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password)


def _apply_schema(conn: psycopg.Connection, root: Path) -> None:
    schema_path = root / "services" / "ops_db_writer" / "schema_v1.sql"
    schema_v2_path = root / "services" / "ops_db_writer" / "schema_v2_market_bar.sql"
    sql = schema_path.read_text(encoding="utf-8")
    if schema_v2_path.exists():
        sql += "\n\n" + schema_v2_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _apply_timescale(conn: psycopg.Connection) -> dict[str, object]:
    enabled = _env_bool("OPS_DB_TIMESCALE_ENABLED", True)
    required = _env_bool("OPS_DB_TIMESCALE_REQUIRED", False)
    compression_enabled = _env_bool("OPS_DB_TIMESCALE_ENABLE_COMPRESSION", False)
    meta: dict[str, Any] = {
        "enabled": enabled,
        "required": required,
        "extension_available": False,
        "hypertables": [],
        "hypertable_attempts": [],
        "retention_policies": [],
        "compression_policies": [],
        "warnings": [],
    }
    if not enabled:
        return meta

    table_specs = [
        {
            "name": "bot_snapshot_minute",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_MINUTE_DAYS",
            "retention_default": 90,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_MINUTE_DAYS",
            "compression_default": 3,
            "segment_by": "bot,variant",
        },
        {
            "name": "fills",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_FILLS_DAYS",
            "retention_default": 365,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_FILLS_DAYS",
            "compression_default": 7,
            "segment_by": "bot,variant,exchange,trading_pair",
        },
        {
            "name": "event_envelope_raw",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_EVENTS_DAYS",
            "retention_default": 30,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_EVENTS_DAYS",
            "compression_default": 2,
            "segment_by": "stream,event_type,instance_name",
        },
        {
            "name": "market_depth_raw",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_DEPTH_RAW_DAYS",
            "retention_default": 7,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_DEPTH_RAW_DAYS",
            "compression_default": 1,
            "segment_by": "connector_name,trading_pair,instance_name",
        },
        {
            "name": "market_depth_sampled",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_DEPTH_SAMPLED_DAYS",
            "retention_default": 30,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_DEPTH_SAMPLED_DAYS",
            "compression_default": 3,
            "segment_by": "connector_name,trading_pair,instance_name",
        },
        {
            "name": "market_depth_rollup_minute",
            "time_col": "bucket_minute_utc",
            "retention_env": "OPS_DB_TS_RETENTION_DEPTH_ROLLUP_DAYS",
            "retention_default": 365,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_DEPTH_ROLLUP_DAYS",
            "compression_default": 7,
            "segment_by": "connector_name,trading_pair,instance_name",
        },
        {
            "name": "market_quote_raw",
            "time_col": "ts_utc",
            "retention_env": "OPS_DB_TS_RETENTION_QUOTE_RAW_DAYS",
            "retention_default": 14,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_QUOTE_RAW_DAYS",
            "compression_default": 2,
            "segment_by": "connector_name,trading_pair",
        },
        {
            "name": "market_quote_bar_minute",
            "time_col": "bucket_minute_utc",
            "retention_env": "OPS_DB_TS_RETENTION_QUOTE_BAR_DAYS",
            "retention_default": 365,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_QUOTE_BAR_DAYS",
            "compression_default": 7,
            "segment_by": "connector_name,trading_pair",
        },
        {
            "name": "market_bar_v2",
            "time_col": "bucket_minute_utc",
            "retention_env": "OPS_DB_TS_RETENTION_QUOTE_BAR_DAYS",
            "retention_default": 365,
            "compression_env": "OPS_DB_TS_COMPRESS_AFTER_QUOTE_BAR_DAYS",
            "compression_default": 7,
            "segment_by": "connector_name,trading_pair,bar_source",
        },
    ]

    def _exec(sql: str, params: tuple | None = None, fetchone: bool = False) -> tuple | None:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone() if fetchone else None

    def _fetchall(sql: str, params: tuple | None = None) -> list[tuple]:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall() or [])

    def _incompatible_unique_constraints(table_name: str, time_col: str) -> list[str]:
        rows = _fetchall(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = current_schema()
              AND t.relname = %s
              AND c.contype IN ('p', 'u')
              AND NOT EXISTS (
                SELECT 1
                FROM unnest(c.conkey) AS key(attnum)
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = key.attnum
                WHERE a.attname = %s
              )
            ORDER BY c.conname
            """,
            (table_name, time_col),
        )
        return [str(r[0]) for r in rows if r and r[0]]

    try:
        _exec("CREATE EXTENSION IF NOT EXISTS timescaledb")
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass  # Justification: best-effort rollback after DB error — connection may be aborted
        if required:
            raise RuntimeError(f"timescaledb_required_but_unavailable: {exc}") from exc
        meta["warnings"].append(f"timescaledb_extension_unavailable: {exc}")
        return meta

    try:
        exists_row = _exec("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb')", fetchone=True)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass  # Justification: best-effort rollback after DB error — connection may be aborted
        if required:
            raise RuntimeError(f"timescaledb_extension_probe_failed: {exc}") from exc
        meta["warnings"].append(f"timescaledb_extension_probe_failed: {exc}")
        return meta

    extension_available = bool(exists_row and exists_row[0])
    meta["extension_available"] = extension_available
    if not extension_available:
        if required:
            raise RuntimeError("timescaledb_required_but_not_installed")
        meta["warnings"].append("timescaledb_not_installed_plain_postgres_mode")
        return meta

    created_hypertables = set()
    for spec in table_specs:
        table_name = str(spec["name"])
        time_col = str(spec["time_col"])
        try:
            incompatible_constraints = _incompatible_unique_constraints(table_name, time_col)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass  # Justification: best-effort rollback after DB error — connection may be aborted
            if required:
                raise RuntimeError(
                    f"timescale_constraint_probe_failed:{table_name}:{time_col}: {exc}"
                ) from exc
            meta["warnings"].append(f"timescale_constraint_probe_failed:{table_name}:{time_col}: {exc}")
            meta["hypertable_attempts"].append(
                {"table": table_name, "status": "failed", "error": f"constraint_probe_failed:{exc}"}
            )
            continue

        if incompatible_constraints:
            reason = (
                "incompatible_unique_constraints_missing_time_column:"
                + ",".join(incompatible_constraints)
            )
            if required:
                raise RuntimeError(f"create_hypertable_blocked:{table_name}:{reason}")
            meta["warnings"].append(f"create_hypertable_blocked:{table_name}:{reason}")
            meta["hypertable_attempts"].append(
                {"table": table_name, "status": "skipped", "reason": reason}
            )
            continue

        try:
            _exec(
                f"SELECT create_hypertable('{table_name}', '{time_col}', if_not_exists => TRUE, migrate_data => TRUE)"
            )
            conn.commit()
            created_hypertables.add(table_name)
            meta["hypertables"].append(table_name)
            meta["hypertable_attempts"].append(
                {"table": table_name, "status": "created", "time_column": time_col}
            )
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass  # Justification: best-effort rollback after DB error — connection may be aborted
            if required:
                raise RuntimeError(f"create_hypertable_failed:{table_name}: {exc}") from exc
            meta["warnings"].append(f"create_hypertable_failed:{table_name}: {exc}")
            meta["hypertable_attempts"].append(
                {"table": table_name, "status": "failed", "error": str(exc)}
            )

    for spec in table_specs:
        table_name = str(spec["name"])
        if table_name not in created_hypertables:
            continue
        days = _env_int(str(spec["retention_env"]), int(spec["retention_default"]))
        if days <= 0:
            continue
        try:
            _exec(
                f"SELECT add_retention_policy('{table_name}', INTERVAL '{days} days', if_not_exists => TRUE)"
            )
            conn.commit()
            meta["retention_policies"].append({"table": table_name, "days": days})
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass  # Justification: best-effort rollback after DB error — connection may be aborted
            if required:
                raise RuntimeError(f"add_retention_policy_failed:{table_name}: {exc}") from exc
            meta["warnings"].append(f"add_retention_policy_failed:{table_name}: {exc}")

    if compression_enabled:
        for spec in table_specs:
            table_name = str(spec["name"])
            if table_name not in created_hypertables:
                continue
            after_days = _env_int(str(spec["compression_env"]), int(spec["compression_default"]))
            if after_days <= 0:
                continue
            try:
                seg = str(spec.get("segment_by", "")).strip()
                if seg:
                    _exec(
                        f"ALTER TABLE {table_name} SET (timescaledb.compress = true, timescaledb.compress_segmentby = '{seg}')"
                    )
                else:
                    _exec(f"ALTER TABLE {table_name} SET (timescaledb.compress = true)")
                _exec(
                    f"SELECT add_compression_policy('{table_name}', INTERVAL '{after_days} days', if_not_exists => TRUE)"
                )
                conn.commit()
                meta["compression_policies"].append({"table": table_name, "days": after_days})
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass  # Justification: best-effort rollback after DB error — connection may be aborted
                if required:
                    raise RuntimeError(f"add_compression_policy_failed:{table_name}: {exc}") from exc
                meta["warnings"].append(f"add_compression_policy_failed:{table_name}: {exc}")

    return meta
