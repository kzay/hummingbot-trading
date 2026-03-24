"""One-shot migration: re-compress existing Parquet files to Zstd + 100K row groups.

Usage:
    python -m scripts.migrate_parquet_zstd --dir data/historical

The script discovers all .parquet files under the given directory, re-writes
each with Zstd compression and 100K row groups using atomic tmp-then-rename,
and verifies row-count equality after reload.

Safety:
- Fails fast if .parquet.tmp files are present (sign of active writer).
- Each file is written to a temporary path first, then atomically renamed.
- Original files can always be re-downloaded from the exchange.
"""
from __future__ import annotations

import argparse
import gc
import logging
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

ROW_GROUP_SIZE = 100_000


def _discover_parquet_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.parquet"))


def _check_active_writers(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.parquet.tmp"))


def migrate_file(path: Path) -> tuple[int, int]:
    """Re-write a single Parquet file with Zstd + row groups.

    Uses pandas read_parquet for I/O (reliable on Windows), then writes
    via pandas to_parquet with Zstd compression and 100K row groups.

    Returns (original_size_bytes, new_size_bytes).
    """
    original_size = path.stat().st_size

    df = pd.read_parquet(path, engine="pyarrow")
    original_rows = len(df)

    tmp_path = path.parent / (path.stem + "._migrate_tmp.parquet")
    df.to_parquet(
        tmp_path,
        index=False,
        compression="zstd",
        engine="pyarrow",
        row_group_size=ROW_GROUP_SIZE,
    )

    del df
    gc.collect()

    verify_rows = pq.read_metadata(tmp_path).num_rows
    if verify_rows != original_rows:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Row count mismatch for {path}: "
            f"expected {original_rows}, got {verify_rows}"
        )

    tmp_path.replace(path)
    new_size = path.stat().st_size
    return original_size, new_size


def run_migration(directory: Path) -> None:
    """Migrate all Parquet files under *directory*."""
    if not directory.is_dir():
        logger.error("Directory does not exist: %s", directory)
        sys.exit(1)

    tmp_files = _check_active_writers(directory)
    if tmp_files:
        logger.error(
            "Found %d .parquet.tmp files — active writer detected. "
            "Quiesce the directory before migrating:\n%s",
            len(tmp_files),
            "\n".join(f"  {f}" for f in tmp_files),
        )
        sys.exit(1)

    files = _discover_parquet_files(directory)
    if not files:
        logger.info("No .parquet files found under %s", directory)
        return

    logger.info("Found %d Parquet files to migrate under %s", len(files), directory)

    total_original = 0
    total_new = 0
    migrated = 0
    errors: list[str] = []

    for path in files:
        try:
            orig, new = migrate_file(path)
            total_original += orig
            total_new += new
            migrated += 1
            logger.info(
                "Migrated %s: %d → %d bytes (%.1f%%)",
                path.name, orig, new, (1 - new / orig) * 100 if orig else 0,
            )
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            logger.error("Failed to migrate %s: %s", path, exc)

    savings = total_original - total_new
    pct = (savings / total_original * 100) if total_original else 0

    print("\n--- Migration Summary ---")
    print(f"Files migrated:    {migrated}/{len(files)}")
    print(f"Original total:    {total_original:,} bytes")
    print(f"New total:         {total_new:,} bytes")
    print(f"Savings:           {savings:,} bytes ({pct:.1f}%)")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors:
            print(f"  {e}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Re-compress Parquet files to Zstd with 100K row groups"
    )
    parser.add_argument(
        "--dir", required=True,
        help="Root directory containing .parquet files",
    )
    args = parser.parse_args()
    run_migration(Path(args.dir))


if __name__ == "__main__":
    main()
