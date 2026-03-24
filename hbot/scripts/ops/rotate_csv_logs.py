"""Rotate CSV log files that exceed size or age thresholds.

Scans ``data/bot*/logs/`` for minute.csv, fills.csv, and daily.csv files.
Files exceeding ``--max-size-mb`` or ``--max-age-days`` are archived to
``<name>_YYYYMMDD.csv.gz`` and a fresh (empty) file is left in place.

Current-day files (protected by ``artifact_retention_policy.json``) are never
rotated unless they exceed the size threshold.

Usage::

    python scripts/ops/rotate_csv_logs.py --apply
    python scripts/ops/rotate_csv_logs.py --dry-run
"""
from __future__ import annotations

import argparse
import gzip
import logging
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_DEFAULT_MAX_SIZE_MB = 100
_DEFAULT_MAX_AGE_DAYS = 30
_CSV_PATTERNS = ("minute.csv", "fills.csv", "daily.csv")


def _archive_name(csv_path: Path) -> Path:
    stem = csv_path.stem
    ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    return csv_path.parent / f"{stem}_{ts}.csv.gz"


def _file_age_days(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 86400.0


def _file_size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def rotate_csv_logs(
    data_root: Path,
    max_size_mb: float = _DEFAULT_MAX_SIZE_MB,
    max_age_days: float = _DEFAULT_MAX_AGE_DAYS,
    apply: bool = False,
) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    for bot_dir in sorted(data_root.glob("bot*")):
        logs_dir = bot_dir / "logs"
        if not logs_dir.is_dir():
            continue
        for csv_path in sorted(logs_dir.rglob("*.csv")):
            if csv_path.name not in _CSV_PATTERNS:
                continue
            size_mb = _file_size_mb(csv_path)
            age_days = _file_age_days(csv_path)
            reason = None
            if size_mb >= max_size_mb:
                reason = f"size={size_mb:.1f}MB >= {max_size_mb}MB"
            elif age_days >= max_age_days:
                reason = f"age={age_days:.0f}d >= {max_age_days}d"
            if reason is None:
                continue

            archive = _archive_name(csv_path)
            action = {
                "file": str(csv_path),
                "archive": str(archive),
                "reason": reason,
                "size_mb": round(size_mb, 2),
                "age_days": round(age_days, 1),
                "applied": False,
            }
            if apply:
                try:
                    with open(csv_path, "rb") as f_in, gzip.open(archive, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                    csv_path.write_text("", encoding="utf-8")
                    action["applied"] = True
                    logger.info("Rotated %s -> %s (%s)", csv_path, archive, reason)
                except Exception as exc:
                    action["error"] = str(exc)
                    logger.error("Failed to rotate %s: %s", csv_path, exc)
            else:
                logger.info("[dry-run] Would rotate %s -> %s (%s)", csv_path, archive, reason)

            actions.append(action)
    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate large or old CSV log files.")
    parser.add_argument("--data-root", type=str, default=str(Path(__file__).resolve().parents[2] / "data"))
    parser.add_argument("--max-size-mb", type=float, default=_DEFAULT_MAX_SIZE_MB)
    parser.add_argument("--max-age-days", type=float, default=_DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--apply", action="store_true", help="Actually rotate files (default is dry-run).")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run mode (default).")
    args = parser.parse_args()

    actions = rotate_csv_logs(
        data_root=Path(args.data_root),
        max_size_mb=args.max_size_mb,
        max_age_days=args.max_age_days,
        apply=args.apply and not args.dry_run,
    )
    logger.info("CSV rotation complete: %d files %s", len(actions), "rotated" if args.apply else "would rotate")


if __name__ == "__main__":
    main()
