#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    import psycopg
except Exception:  # pragma: no cover - optional in lightweight environments.
    psycopg = None  # type: ignore[assignment]

_CANONICAL_TABLES = ("bot_snapshot_minute", "fills", "event_envelope_raw")
_SAFE_DB_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_report(report_dir: Path, stem: str, payload: dict[str, object]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    ts_path = report_dir / f"{stem}_{stamp}.json"
    latest_path = report_dir / f"{stem}_latest.json"
    raw = json.dumps(payload, indent=2)
    ts_path.write_text(raw, encoding="utf-8")
    latest_path.write_text(raw, encoding="utf-8")


def _safe_db_name(name: str) -> str:
    clean = str(name).strip()
    if not clean or not _SAFE_DB_RE.match(clean):
        raise ValueError(f"unsafe_db_name:{name}")
    return clean


def _latest_manifest(backup_dir: Path) -> Path | None:
    manifests = sorted(backup_dir.glob("pg_backup_*.manifest.json"))
    return manifests[-1] if manifests else None


def _connect_db(host: str, port: int, dbname: str, user: str, password: str):
    if psycopg is None:
        raise RuntimeError("psycopg_not_installed")
    return psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password)


def _create_fresh_db(host: str, port: int, admin_db: str, user: str, password: str, restore_db: str) -> None:
    restore_db = _safe_db_name(restore_db)
    admin_db = _safe_db_name(admin_db)
    with _connect_db(host, port, admin_db, user, password) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{restore_db}"')
            cur.execute(f'CREATE DATABASE "{restore_db}"')


def _drop_db(host: str, port: int, admin_db: str, user: str, password: str, restore_db: str) -> None:
    restore_db = _safe_db_name(restore_db)
    admin_db = _safe_db_name(admin_db)
    with _connect_db(host, port, admin_db, user, password) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{restore_db}"')


def _restore_dump_with_psql(
    backup_file: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    restore_db: str,
    timeout_sec: int,
) -> tuple[int, str, str]:
    psql_bin = shutil.which("psql")
    if not psql_bin:
        return 127, "", "psql_not_found_in_path"
    env = dict(os.environ)
    env["PGPASSWORD"] = password
    try:
        with gzip.open(backup_file, "rb") as fp:
            sql_bytes = fp.read()
    except Exception as exc:
        return 2, "", f"backup_decompress_failed:{exc}"
    cmd = [psql_bin, "-h", host, "-p", str(port), "-U", user, "-d", restore_db, "-v", "ON_ERROR_STOP=1"]
    try:
        proc = subprocess.run(cmd, input=sql_bytes, capture_output=True, env=env, timeout=timeout_sec, check=False)
        stdout = (proc.stdout or b"").decode("utf-8", errors="ignore")
        stderr = (proc.stderr or b"").decode("utf-8", errors="ignore")
        return int(proc.returncode), stdout, stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"restore_timeout_{timeout_sec}s"
    except Exception as exc:
        return 2, "", f"restore_exception:{exc}"


def _fetch_table_counts(host: str, port: int, dbname: str, user: str, password: str) -> dict[str, int]:
    out: dict[str, int] = {}
    with _connect_db(host, port, dbname, user, password) as conn, conn.cursor() as cur:
        for table in _CANONICAL_TABLES:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                row = cur.fetchone()
                out[table] = int(row[0] if row else 0)
            except Exception:
                conn.rollback()
                out[table] = -1
    return out


def _counts_match(expected_counts: dict[str, int], restored_counts: dict[str, int]) -> bool:
    if not expected_counts:
        return all(int(v) >= 0 for v in restored_counts.values())
    for table, expected in expected_counts.items():
        if int(restored_counts.get(table, -1)) != int(expected):
            return False
    return True


def run_restore_drill(
    backup_dir: Path,
    report_dir: Path,
    host: str,
    port: int,
    source_db: str,
    admin_db: str,
    user: str,
    password: str,
    restore_db_prefix: str,
    timeout_sec: int,
    keep_restored_db: bool,
    require_parity_sidecar: bool,
) -> dict[str, object]:
    start = time.time()
    report: dict[str, object] = {
        "ts_utc": _utc_now(),
        "status": "fail",
        "backup_manifest": "",
        "backup_file": "",
        "restore_db": "",
        "restore_rc": 2,
        "restore_stdout": "",
        "restore_stderr": "",
        "canonical_tables_restored": False,
        "counts_match_source": False,
        "expected_source_counts": {},
        "restored_counts": {},
        "parity_state_recovered": False,
        "parity_sidecar_path": "",
        "parity_sidecar_sha256": "",
        "parity_sidecar_sha256_expected": "",
        "duration_sec": 0.0,
        "error": "",
    }

    manifest_path = _latest_manifest(backup_dir)
    if manifest_path is None:
        report["error"] = f"no_backup_manifest_in:{backup_dir}"
        report["duration_sec"] = round(time.time() - start, 3)
        _write_report(report_dir, "ops_db_restore_drill", report)
        return report

    manifest = _read_json(manifest_path)
    report["backup_manifest"] = str(manifest_path)
    backup_file = Path(str(manifest.get("backup_file", "")).strip())
    if not backup_file.exists():
        report["error"] = f"backup_file_missing:{backup_file}"
        report["duration_sec"] = round(time.time() - start, 3)
        _write_report(report_dir, "ops_db_restore_drill", report)
        return report
    report["backup_file"] = str(backup_file)

    expected_source_counts: dict[str, int] = {}
    raw_counts = manifest.get("source_counts", {})
    if isinstance(raw_counts, dict):
        for table in _CANONICAL_TABLES:
            try:
                expected_source_counts[table] = int(raw_counts.get(table, -1))
            except Exception:
                expected_source_counts[table] = -1
    if not expected_source_counts or any(v < 0 for v in expected_source_counts.values()):
        try:
            expected_source_counts = _fetch_table_counts(host, port, source_db, user, password)
        except Exception:
            expected_source_counts = {}
    report["expected_source_counts"] = expected_source_counts

    restore_db = _safe_db_name(f"{restore_db_prefix}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}")
    report["restore_db"] = restore_db
    try:
        _create_fresh_db(host, port, admin_db, user, password, restore_db)
    except Exception as exc:
        report["error"] = f"restore_db_create_failed:{exc}"
        report["duration_sec"] = round(time.time() - start, 3)
        _write_report(report_dir, "ops_db_restore_drill", report)
        return report

    restore_rc, restore_out, restore_err = _restore_dump_with_psql(
        backup_file=backup_file,
        host=host,
        port=port,
        user=user,
        password=password,
        restore_db=restore_db,
        timeout_sec=timeout_sec,
    )
    report["restore_rc"] = int(restore_rc)
    report["restore_stdout"] = restore_out[:2000]
    report["restore_stderr"] = restore_err[:2000]

    restored_counts: dict[str, int] = {}
    if restore_rc == 0:
        try:
            restored_counts = _fetch_table_counts(host, port, restore_db, user, password)
        except Exception as exc:
            report["error"] = f"restored_count_query_failed:{exc}"
    report["restored_counts"] = restored_counts
    canonical_tables_restored = bool(restored_counts) and all(int(v) >= 0 for v in restored_counts.values())
    counts_match = _counts_match(expected_source_counts, restored_counts)
    report["canonical_tables_restored"] = canonical_tables_restored
    report["counts_match_source"] = counts_match

    parity_sidecar = manifest.get("parity_sidecar", {})
    parity_sidecar = parity_sidecar if isinstance(parity_sidecar, dict) else {}
    sidecar_path = Path(str(parity_sidecar.get("path", "")).strip())
    sidecar_sha_expected = str(parity_sidecar.get("sha256", "")).strip()
    sidecar_sha_actual = _sha256_file(sidecar_path)
    report["parity_sidecar_path"] = str(sidecar_path)
    report["parity_sidecar_sha256_expected"] = sidecar_sha_expected
    report["parity_sidecar_sha256"] = sidecar_sha_actual
    parity_state_recovered = bool(sidecar_path.exists() and sidecar_sha_expected and sidecar_sha_actual == sidecar_sha_expected)
    if parity_state_recovered:
        recovered_path = report_dir / "ops_db_restore_drill_parity_latest.json"
        shutil.copy2(sidecar_path, recovered_path)
    if require_parity_sidecar:
        report["parity_state_recovered"] = parity_state_recovered
    else:
        report["parity_state_recovered"] = parity_state_recovered or (not sidecar_path.exists())

    if not keep_restored_db:
        try:
            _drop_db(host, port, admin_db, user, password, restore_db)
        except Exception as exc:
            # Non-fatal for drill verdict, but preserve for operator visibility.
            report["error"] = str(report.get("error", "") or f"restore_db_cleanup_failed:{exc}")

    all_ok = (
        int(restore_rc) == 0
        and bool(report.get("canonical_tables_restored", False))
        and bool(report.get("counts_match_source", False))
        and bool(report.get("parity_state_recovered", False))
    )
    report["status"] = "pass" if all_ok else "fail"
    report["duration_sec"] = round(time.time() - start, 3)
    _write_report(report_dir, "ops_db_restore_drill", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ops DB restore drill to a fresh database.")
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    parser.add_argument("--backup-dir", default=os.getenv("OPS_DB_BACKUP_DIR", str(root / "backups" / "postgres")))
    parser.add_argument("--report-dir", default=os.getenv("OPS_DB_BACKUP_REPORT_DIR", str(root / "reports" / "ops")))
    parser.add_argument("--restore-db-prefix", default=os.getenv("OPS_DB_RESTORE_DRILL_DB_PREFIX", "kzay_capital_ops_restore_drill"))
    parser.add_argument("--timeout-sec", type=int, default=int(os.getenv("OPS_DB_RESTORE_DRILL_TIMEOUT_SEC", "600")))
    parser.add_argument("--keep-restored-db", action="store_true", help="Do not drop restored drill DB after verification.")
    parser.add_argument(
        "--require-parity-sidecar",
        action="store_true",
        default=True,
        help="Require parity sidecar hash verification to pass drill (default: true).",
    )
    parser.add_argument(
        "--no-require-parity-sidecar",
        action="store_false",
        dest="require_parity_sidecar",
        help="Allow drill pass when parity sidecar is unavailable.",
    )
    args = parser.parse_args()

    host = os.getenv("OPS_DB_HOST", "postgres")
    port = int(os.getenv("OPS_DB_PORT", "5432"))
    source_db = os.getenv("OPS_DB_NAME", "kzay_capital_ops")
    admin_db = os.getenv("OPS_DB_ADMIN_DB", "postgres")
    user = os.getenv("OPS_DB_USER", "hbot")
    password = os.getenv("OPS_DB_PASSWORD", "kzay_capital_dev_password")

    payload = run_restore_drill(
        backup_dir=Path(args.backup_dir),
        report_dir=Path(args.report_dir),
        host=host,
        port=port,
        source_db=source_db,
        admin_db=admin_db,
        user=user,
        password=password,
        restore_db_prefix=str(args.restore_db_prefix),
        timeout_sec=int(args.timeout_sec),
        keep_restored_db=bool(args.keep_restored_db),
        require_parity_sidecar=bool(args.require_parity_sidecar),
    )
    print(f"[ops-db-restore-drill] status={payload.get('status')} duration_sec={payload.get('duration_sec')}")
    print(f"[ops-db-restore-drill] evidence={Path(args.report_dir) / 'ops_db_restore_drill_latest.json'}")
    return 0 if str(payload.get("status", "fail")) == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
