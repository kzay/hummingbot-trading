"""Event store JSONL archival script.

Compresses and archives event store files older than N days.
Deletes originals after archival to save disk space.

Usage::

    python scripts/ops/archive_event_store.py --once
    python scripts/ops/archive_event_store.py --interval-hours 24
"""
from __future__ import annotations

import argparse
import gzip
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def archive_old_files(
    event_store_dir: Path,
    archive_dir: Path,
    max_age_days: int,
) -> int:
    """Compress and archive JSONL files older than max_age_days. Returns count archived."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    cutoff_ts = time.time() - max_age_days * 86400
    archived = 0

    for jsonl_file in sorted(event_store_dir.glob("events_*.jsonl")):
        try:
            mtime = jsonl_file.stat().st_mtime
            if mtime >= cutoff_ts:
                continue
            gz_path = archive_dir / f"{jsonl_file.name}.gz"
            with jsonl_file.open("rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            original_mb = jsonl_file.stat().st_size / (1024 * 1024)
            compressed_mb = gz_path.stat().st_size / (1024 * 1024)
            jsonl_file.unlink()
            archived += 1
            logger.info("Archived %s (%.1f MB → %.1f MB)", jsonl_file.name, original_mb, compressed_mb)
        except Exception:
            logger.error("Failed to archive %s", jsonl_file.name, exc_info=True)

    return archived


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive old event store JSONL files")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-hours", type=int, default=24)
    parser.add_argument("--max-age-days", type=int, default=7)
    parser.add_argument("--event-store-dir", default="/workspace/hbot/reports/event_store")
    parser.add_argument("--archive-dir", default="/workspace/hbot/backups/event_store")
    args = parser.parse_args()

    event_store_dir = Path(args.event_store_dir)
    archive_dir = Path(args.archive_dir)

    if args.once:
        count = archive_old_files(event_store_dir, archive_dir, args.max_age_days)
        logger.info("Archived %d file(s)", count)
        sys.exit(0)

    while True:
        count = archive_old_files(event_store_dir, archive_dir, args.max_age_days)
        if count > 0:
            logger.info("Archived %d file(s)", count)
        time.sleep(args.interval_hours * 3600)


if __name__ == "__main__":
    main()
