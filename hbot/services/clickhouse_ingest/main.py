from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _http_query(
    host: str,
    port: int,
    database: str,
    query: str,
    user: str,
    password: str,
    body: str = "",
    timeout_sec: float = 10.0,
) -> Tuple[bool, str]:
    params = urllib.parse.urlencode({"database": database, "query": query})
    url = f"http://{host}:{port}/?{params}"
    req = urllib.request.Request(url=url, data=body.encode("utf-8"), method="POST")
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    if user:
        req.add_header("Authorization", _auth_header(user=user, password=password))
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            out = resp.read().decode("utf-8", errors="ignore")
        return True, out
    except Exception as exc:
        return False, str(exc)


def _ensure_schema(host: str, port: int, database: str, table: str, user: str, password: str) -> Tuple[bool, str]:
    stmts = [
        f"CREATE DATABASE IF NOT EXISTS {database}",
        f"""
        CREATE TABLE IF NOT EXISTS {database}.{table} (
          ingest_ts DateTime64(3, 'UTC') DEFAULT now64(3),
          event_ts Nullable(DateTime64(3, 'UTC')),
          event_id String,
          correlation_id String,
          event_type String,
          producer String,
          instance_name String,
          controller_id String,
          source_file String,
          source_line UInt64,
          payload_json String,
          raw_json String
        ) ENGINE = MergeTree
        ORDER BY (source_file, source_line)
        """.strip(),
    ]
    for stmt in stmts:
        ok, msg = _http_query(
            host=host,
            port=port,
            database=database,
            query=stmt,
            user=user,
            password=password,
            body="",
        )
        if not ok:
            return False, msg
    return True, "ok"


def _event_row(obj: Dict[str, object], source_file: str, source_line: int) -> Dict[str, object]:
    payload = obj.get("payload", {}) if isinstance(obj.get("payload"), dict) else {}
    return {
        "event_ts": str(obj.get("ts_utc", "")).strip() or None,
        "event_id": str(obj.get("event_id", "")).strip(),
        "correlation_id": str(obj.get("correlation_id", "")).strip(),
        "event_type": str(obj.get("event_type", "")).strip(),
        "producer": str(obj.get("producer", "")).strip(),
        "instance_name": str(obj.get("instance_name", "")).strip(),
        "controller_id": str(obj.get("controller_id", "")).strip(),
        "source_file": source_file,
        "source_line": int(source_line),
        "payload_json": json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
        "raw_json": json.dumps(obj, separators=(",", ":"), ensure_ascii=True),
    }


def _insert_rows(
    host: str,
    port: int,
    database: str,
    table: str,
    user: str,
    password: str,
    rows: List[Dict[str, object]],
) -> Tuple[bool, str]:
    if not rows:
        return True, "no_rows"
    query = f"INSERT INTO {database}.{table} FORMAT JSONEachRow"
    body = "\n".join(json.dumps(r, separators=(",", ":"), ensure_ascii=True) for r in rows) + "\n"
    return _http_query(
        host=host,
        port=port,
        database=database,
        query=query,
        user=user,
        password=password,
        body=body,
        timeout_sec=30.0,
    )


def run_once(root: Path, dry_run: bool = False) -> Dict[str, object]:
    reports_root = Path(os.getenv("HB_REPORTS_ROOT", str(root / "reports")))
    event_store_root = reports_root / "event_store"
    ingest_root = reports_root / "clickhouse_ingest"
    state_path = ingest_root / "state.json"

    ch_host = os.getenv("CH_HOST", "clickhouse")
    ch_port = int(os.getenv("CH_HTTP_PORT", "8123"))
    ch_db = os.getenv("CH_DB", "hbot_events")
    ch_table = os.getenv("CH_TABLE", "event_store_raw_v1")
    ch_user = os.getenv("CH_USER", "default")
    ch_password = os.getenv("CH_PASSWORD", "")
    batch_size = max(100, int(os.getenv("CH_INGEST_BATCH_SIZE", "2000")))

    state = _read_json(state_path)
    files_state = state.get("files", {}) if isinstance(state.get("files"), dict) else {}

    result: Dict[str, object] = {
        "ts_utc": _utc_now(),
        "status": "pass",
        "dry_run": bool(dry_run),
        "clickhouse": {
            "host": ch_host,
            "port": ch_port,
            "database": ch_db,
            "table": ch_table,
        },
        "files_seen": 0,
        "files_with_new_rows": 0,
        "rows_inserted": 0,
        "errors": [],
    }

    if not dry_run:
        ok, msg = _ensure_schema(ch_host, ch_port, ch_db, ch_table, ch_user, ch_password)
        if not ok:
            result["status"] = "fail"
            result["errors"] = [f"schema_init_failed:{msg}"]
            return result

    event_files = sorted(event_store_root.glob("events_*.jsonl"))
    result["files_seen"] = len(event_files)

    for fp in event_files:
        source_file = str(fp.resolve())
        prev_line = int(files_state.get(source_file, 0))
        current_line = 0
        rows: List[Dict[str, object]] = []
        inserted_for_file = 0
        try:
            with fp.open("r", encoding="utf-8", errors="ignore") as f:
                for idx, line in enumerate(f, start=1):
                    current_line = idx
                    if idx <= prev_line:
                        continue
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    rows.append(_event_row(obj=obj, source_file=source_file, source_line=idx))
                    if len(rows) >= batch_size:
                        if not dry_run:
                            ok, msg = _insert_rows(ch_host, ch_port, ch_db, ch_table, ch_user, ch_password, rows)
                            if not ok:
                                raise RuntimeError(f"insert_failed:{msg}")
                        inserted_for_file += len(rows)
                        rows = []
            if rows:
                if not dry_run:
                    ok, msg = _insert_rows(ch_host, ch_port, ch_db, ch_table, ch_user, ch_password, rows)
                    if not ok:
                        raise RuntimeError(f"insert_failed:{msg}")
                inserted_for_file += len(rows)
            files_state[source_file] = current_line
            if inserted_for_file > 0:
                result["files_with_new_rows"] = int(result["files_with_new_rows"]) + 1
            result["rows_inserted"] = int(result["rows_inserted"]) + inserted_for_file
        except Exception as exc:
            result["status"] = "fail"
            errs = result.get("errors", [])
            errs = errs if isinstance(errs, list) else []
            errs.append(f"{fp.name}:{exc}")
            result["errors"] = errs

    next_state = {"ts_utc": _utc_now(), "files": files_state}
    _write_json(state_path, next_state)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest event-store JSONL into ClickHouse.")
    parser.add_argument("--once", action="store_true", help="Run one ingestion cycle and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Do not connect/insert into ClickHouse.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports_root = Path(os.getenv("HB_REPORTS_ROOT", str(root / "reports")))
    out_root = reports_root / "clickhouse_ingest"
    out_root.mkdir(parents=True, exist_ok=True)
    interval_sec = max(30, int(os.getenv("CH_INGEST_INTERVAL_SEC", "120")))

    def _persist(payload: Dict[str, object]) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = out_root / f"clickhouse_ingest_{stamp}.json"
        _write_json(out, payload)
        _write_json(out_root / "latest.json", payload)
        print(f"[clickhouse-ingest] status={payload.get('status')}")
        print(f"[clickhouse-ingest] rows_inserted={payload.get('rows_inserted', 0)}")
        print(f"[clickhouse-ingest] evidence={out}")

    if args.once:
        _persist(run_once(root=root, dry_run=bool(args.dry_run)))
        return

    while True:
        _persist(run_once(root=root, dry_run=bool(args.dry_run)))
        time.sleep(interval_sec)


if __name__ == "__main__":
    main()
