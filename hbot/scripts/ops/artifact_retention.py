"""Daily paper-state backup script.

Copies key bot1 paper trading files to a date-keyed archive directory.
Files are COPIED (not moved) so the bot continues to append to the originals.

Usage::

    python scripts/ops/artifact_retention.py --date 2026-02-26
    python scripts/ops/artifact_retention.py              # defaults to today UTC
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_SOURCE_FILES = [
    "data/bot1/logs/epp_v24/bot1_a/minute.csv",
    "data/bot1/logs/epp_v24/bot1_a/fills.csv",
    "data/bot1/logs/epp_v24/bot1_a/paper_desk_v2.json",
]


def backup_paper_state(root: Path, date_str: str) -> None:
    """Copy key paper-trading state files to data/bot1/archive/{date_str}/."""
    archive_dir = root / "data" / "bot1" / "archive" / date_str
    archive_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for rel in _SOURCE_FILES:
        src = root / rel
        if not src.exists():
            logger.warning("Source file not found, skipping: %s", src)
            continue
        dst = archive_dir / src.name
        shutil.copy2(str(src), str(dst))
        logger.info("Backed up %s -> %s", src, dst)
        copied += 1

    if copied == 0:
        logger.warning("No files found to back up for date %s", date_str)
    else:
        logger.info("Backup complete: %d file(s) -> %s", copied, archive_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up paper-state files to date-keyed archive")
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).strftime("%Y%m%d"),
        help="Archive date key (default: today UTC, format YYYYMMDD)",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Project root (default: auto-detect from script location)",
    )
    args = parser.parse_args()

    if args.root:
        root = Path(args.root)
    else:
        root = Path(__file__).resolve().parents[2]

    if not root.exists():
        logger.error("Root directory does not exist: %s", root)
        sys.exit(1)

    backup_paper_state(root, args.date)


if __name__ == "__main__":
    main()
