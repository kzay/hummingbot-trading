#!/usr/bin/env python3
"""Rotate old report files under hbot/reports/."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

SECONDS_PER_DAY = 86400
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_DIRS = (
    ("reports/parity", 7, False),
    ("reports/reconciliation", 14, False),
    ("reports/verification", 14, True),
)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )


def _process_dir(
    rel: str,
    retain_days: int,
    verification_tmp: bool,
    dry_run: bool,
) -> int:
    """Return count of files removed or that would be removed."""
    root = WORKSPACE_ROOT / rel
    if not root.is_dir():
        logging.warning("Skip missing directory: %s", root)
        return 0
    cutoff = time.time() - retain_days * SECONDS_PER_DAY
    would = 0
    for path in root.iterdir():
        if not path.is_file():
            continue
        remove = path.suffix.lower() == ".tmp" if verification_tmp else False
        if not remove and path.stat().st_mtime >= cutoff:
            continue
        would += 1
        logging.info("%s: %s", "would delete" if dry_run else "deleting", path)
        if not dry_run:
            path.unlink()
    return would


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate report files by age and policy.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log actions only; do not delete files.",
    )
    args = parser.parse_args()
    _setup_logging()
    if args.dry_run:
        logging.info("Dry run: no files will be removed.")
    total_candidates = 0
    for rel, days, ver_tmp in REPORT_DIRS:
        n = _process_dir(rel, days, ver_tmp, args.dry_run)
        total_candidates += n
        logging.info(
            "Summary %s: %d file(s) %s",
            rel,
            n,
            "would be removed" if args.dry_run else "removed",
        )
    logging.info(
        "Total: %d file(s) %s",
        total_candidates,
        "would be removed" if args.dry_run else "removed",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
