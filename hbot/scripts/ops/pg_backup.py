"""PostgreSQL backup script with verification evidence.

This script creates compressed logical backups (pg_dump + gzip), keeps a
retention window, and writes machine-readable evidence in ``reports/ops``.
It also stores a parity sidecar snapshot + manifest so restore drills can
verify canonical-table recovery and parity-state continuity.

Usage::

    python scripts/ops/pg_backup.py --once
    python scripts/ops/pg_backup.py --interval-hours 24
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

try:
    import psycopg
except Exception:  # pragma: no cover - optional in lightweight environments.
    psycopg = None  # type: ignore[assignment]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_CANONICAL_TABLES = ("bot_snapshot_minute", "fills", "event_envelope_raw")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_report(report_dir: Path, stem: str, payload: Dict[str, object]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ts_path = report_dir / f"{stem}_{stamp}.json"
    latest_path = report_dir / f"{stem}_latest.json"
    raw = json.dumps(payload, indent=2)
    ts_path.write_text(raw, encoding="utf-8")
    latest_path.write_text(raw, encoding="utf-8")


def _verify_gzip(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    try:
        with gzip.open(path, "rb") as fp:
            fp.read(1024)
        return True
    except Exception:
        return False


def _copy_parity_sidecar(parity_latest_path: Path, backup_dir: Path, stamp: str) -> Dict[str, object]:
    result: Dict[str, object] = {
        "path": "",
        "sha256": "",
        "ts_utc": "",
        "status": "missing",
    }
    if not parity_latest_path.exists():
        return result
    sidecar = backup_dir / f"pg_backup_{stamp}.parity_latest.json"
    shutil.copy2(parity_latest_path, sidecar)
    parity_payload: Dict[str, object] = {}
    try:
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            parity_payload = raw
    except Exception:
        parity_payload = {}
    result["path"] = str(sidecar)
    result["sha256"] = _sha256_file(sidecar)
    result["ts_utc"] = str(parity_payload.get("ts_utc", "")).strip()
    result["status"] = str(parity_payload.get("status", "")).strip()
    return result


def _fetch_canonical_counts(host: str, port: int, dbname: str, user: str, password: str) -> Dict[str, object]:
    out: Dict[str, object] = {"available": False, "counts": {}, "error": ""}
    if psycopg is None:
        out["error"] = "psycopg_not_installed"
        return out
    try:
        with psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password) as conn:
            counts: Dict[str, int] = {}
            with conn.cursor() as cur:
                for table in _CANONICAL_TABLES:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    row = cur.fetchone()
                    counts[table] = int(row[0] if row else 0)
            out["available"] = True
            out["counts"] = counts
            return out
    except Exception as exc:
        out["error"] = str(exc)
        return out


def _latest_backup_age_hours(backups: List[Path]) -> float:
    if not backups:
        return 1e9
    latest = backups[-1]
    try:
        age_sec = max(0.0, time.time() - float(latest.stat().st_mtime))
    except Exception:
        return 1e9
    return age_sec / 3600.0


def run_backup(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
    backup_dir: Path,
    retention_count: int,
    report_dir: Path,
    parity_latest_path: Path,
    timeout_sec: int = 300,
) -> Dict[str, object]:
    """Run a backup and return structured evidence payload."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = backup_dir / f"pg_backup_{stamp}.sql.gz"
    manifest_file = backup_dir / f"pg_backup_{stamp}.manifest.json"
    env = dict(os.environ)
    env["PGPASSWORD"] = password

    report: Dict[str, object] = {
        "ts_utc": _utc_now(),
        "status": "fail",
        "host": host,
        "port": int(port),
        "dbname": dbname,
        "backup_file": str(out_file),
        "manifest_file": str(manifest_file),
        "backup_verified": False,
        "backup_size_bytes": 0,
        "backup_sha256": "",
        "retention_count": int(retention_count),
        "backup_count_after_prune": 0,
        "backup_freshness_hours": 1e9,
        "source_counts": {},
        "source_counts_available": False,
        "source_counts_error": "",
        "parity_sidecar": {},
        "error": "",
    }

    # Use shell redirection for efficient streaming compression.
    cmd = f'pg_dump -h {host} -p {port} -U {user} -d {dbname} | gzip > "{out_file}"'
    try:
        result = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True, timeout=timeout_sec)
        if result.returncode != 0:
            report["error"] = (result.stderr or "pg_dump_failed").strip()[:500]
            if out_file.exists():
                out_file.unlink()
            _write_report(report_dir, "ops_db_backup", report)
            return report
    except subprocess.TimeoutExpired:
        report["error"] = f"pg_dump_timeout_{timeout_sec}s"
        _write_report(report_dir, "ops_db_backup", report)
        return report
    except Exception as exc:
        report["error"] = f"pg_dump_exception:{exc}"
        _write_report(report_dir, "ops_db_backup", report)
        return report

    report["backup_verified"] = bool(_verify_gzip(out_file))
    if not bool(report["backup_verified"]):
        report["error"] = "gzip_verify_failed"
        if out_file.exists():
            out_file.unlink()
        _write_report(report_dir, "ops_db_backup", report)
        return report

    report["backup_size_bytes"] = int(out_file.stat().st_size if out_file.exists() else 0)
    report["backup_sha256"] = _sha256_file(out_file)
    parity_sidecar = _copy_parity_sidecar(parity_latest_path, backup_dir, stamp)
    report["parity_sidecar"] = parity_sidecar

    source_counts = _fetch_canonical_counts(host, port, dbname, user, password)
    report["source_counts"] = source_counts.get("counts", {})
    report["source_counts_available"] = bool(source_counts.get("available", False))
    report["source_counts_error"] = str(source_counts.get("error", "")).strip()

    manifest = {
        "ts_utc": _utc_now(),
        "backup_file": str(out_file),
        "backup_sha256": report["backup_sha256"],
        "backup_size_bytes": report["backup_size_bytes"],
        "source_counts": report["source_counts"],
        "source_counts_available": report["source_counts_available"],
        "source_counts_error": report["source_counts_error"],
        "parity_sidecar": parity_sidecar,
    }
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    backups = sorted(backup_dir.glob("pg_backup_*.sql.gz"))
    while len(backups) > retention_count:
        old = backups.pop(0)
        old.unlink(missing_ok=True)
        old_manifest = old.with_name(old.name.replace(".sql.gz", ".manifest.json"))
        old_manifest.unlink(missing_ok=True)
        old_parity = old.with_name(old.name.replace(".sql.gz", ".parity_latest.json"))
        old_parity.unlink(missing_ok=True)
        logger.info("Pruned old backup set: %s", old.name)

    backups = sorted(backup_dir.glob("pg_backup_*.sql.gz"))
    report["backup_count_after_prune"] = len(backups)
    report["backup_freshness_hours"] = float(_latest_backup_age_hours(backups))
    report["status"] = "pass"
    _write_report(report_dir, "ops_db_backup", report)
    logger.info("Backup created: %s", out_file.name)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="PostgreSQL backup with retention + evidence")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-hours", type=int, default=int(os.getenv("OPS_DB_BACKUP_INTERVAL_HOURS", "24")))
    parser.add_argument("--retention-count", type=int, default=int(os.getenv("OPS_DB_BACKUP_RETENTION_COUNT", "7")))
    parser.add_argument("--backup-dir", default=os.getenv("OPS_DB_BACKUP_DIR", "/workspace/hbot/backups/postgres"))
    parser.add_argument("--report-dir", default=os.getenv("OPS_DB_BACKUP_REPORT_DIR", "/workspace/hbot/reports/ops"))
    parser.add_argument(
        "--parity-latest-path",
        default=os.getenv("OPS_DB_PARITY_LATEST_PATH", "/workspace/hbot/reports/parity/latest.json"),
    )
    parser.add_argument("--timeout-sec", type=int, default=int(os.getenv("OPS_DB_BACKUP_TIMEOUT_SEC", "300")))
    args = parser.parse_args()

    host = os.getenv("OPS_DB_HOST", "postgres")
    port = int(os.getenv("OPS_DB_PORT", "5432"))
    dbname = os.getenv("OPS_DB_NAME", "kzay_capital_ops")
    user = os.getenv("OPS_DB_USER", "kzay_capital")
    password = os.getenv("OPS_DB_PASSWORD", "kzay_capital_dev_password")
    backup_dir = Path(args.backup_dir)
    report_dir = Path(args.report_dir)
    parity_latest_path = Path(args.parity_latest_path)

    if args.once:
        payload = run_backup(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            backup_dir=backup_dir,
            retention_count=int(args.retention_count),
            report_dir=report_dir,
            parity_latest_path=parity_latest_path,
            timeout_sec=int(args.timeout_sec),
        )
        print(f"[pg-backup] status={payload.get('status')}")
        print(f"[pg-backup] evidence={report_dir / 'ops_db_backup_latest.json'}")
        sys.exit(0 if str(payload.get("status", "fail")) == "pass" else 1)

    while True:
        payload = run_backup(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            backup_dir=backup_dir,
            retention_count=int(args.retention_count),
            report_dir=report_dir,
            parity_latest_path=parity_latest_path,
            timeout_sec=int(args.timeout_sec),
        )
        logger.info("[pg-backup] status=%s", payload.get("status"))
        time.sleep(max(1, int(args.interval_hours)) * 3600)


if __name__ == "__main__":
    main()
