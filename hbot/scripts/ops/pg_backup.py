"""PostgreSQL backup script.

Runs ``pg_dump`` and stores the output with timestamp-based naming.
Retains the last N backups and deletes older ones.

Usage::

    python scripts/ops/pg_backup.py --once
    python scripts/ops/pg_backup.py --interval-hours 24
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_backup(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
    backup_dir: Path,
    retention_count: int,
) -> bool:
    """Run pg_dump and store the result. Returns True on success."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = backup_dir / f"pg_backup_{stamp}.sql.gz"

    env = dict(os.environ)
    env["PGPASSWORD"] = password

    cmd = f"pg_dump -h {host} -p {port} -U {user} -d {dbname} | gzip > {out_file}"
    try:
        result = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("pg_dump failed: %s", result.stderr[:500])
            if out_file.exists():
                out_file.unlink()
            return False
        size_mb = out_file.stat().st_size / (1024 * 1024)
        logger.info("Backup created: %s (%.1f MB)", out_file.name, size_mb)
    except subprocess.TimeoutExpired:
        logger.error("pg_dump timed out after 300s")
        return False
    except Exception:
        logger.error("pg_dump failed", exc_info=True)
        return False

    backups = sorted(backup_dir.glob("pg_backup_*.sql.gz"))
    while len(backups) > retention_count:
        old = backups.pop(0)
        old.unlink()
        logger.info("Pruned old backup: %s", old.name)

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="PostgreSQL backup with retention")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-hours", type=int, default=24)
    parser.add_argument("--retention-count", type=int, default=7)
    parser.add_argument("--backup-dir", default="/workspace/hbot/backups/postgres")
    args = parser.parse_args()

    host = os.getenv("OPS_DB_HOST", "postgres")
    port = int(os.getenv("OPS_DB_PORT", "5432"))
    dbname = os.getenv("OPS_DB_NAME", "hbot_ops")
    user = os.getenv("OPS_DB_USER", "hbot")
    password = os.getenv("OPS_DB_PASSWORD", "hbot_dev_password")
    backup_dir = Path(args.backup_dir)

    if args.once:
        success = run_backup(host, port, dbname, user, password, backup_dir, args.retention_count)
        sys.exit(0 if success else 1)

    while True:
        run_backup(host, port, dbname, user, password, backup_dir, args.retention_count)
        time.sleep(args.interval_hours * 3600)


if __name__ == "__main__":
    main()
