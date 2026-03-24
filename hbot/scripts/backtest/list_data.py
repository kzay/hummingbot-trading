"""CLI: List available historical datasets in the data catalog.

Usage:
    python -m scripts.backtest.list_data
    python -m scripts.backtest.list_data --dir data/historical
"""
from __future__ import annotations

import argparse
from datetime import UTC
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="List available historical datasets")
    ap.add_argument("--dir", default="data/historical", help="Data base directory")
    args = ap.parse_args()

    from controllers.backtesting.data_catalog import DataCatalog

    catalog = DataCatalog(base_dir=Path(args.dir))
    datasets = catalog.list_datasets()

    if not datasets:
        print("No datasets found. Download data with: python -m scripts.backtest.download_data")
        return

    # Header
    print(f"{'Exchange':<12} {'Pair':<15} {'Resolution':<12} {'Rows':>10} {'Start':>12} {'End':>12} {'Size':>10}")
    print("-" * 85)

    for ds in datasets:
        from datetime import datetime
        start = datetime.fromtimestamp(ds["start_ms"] / 1000, tz=UTC).strftime("%Y-%m-%d")
        end = datetime.fromtimestamp(ds["end_ms"] / 1000, tz=UTC).strftime("%Y-%m-%d")
        size_mb = ds.get("file_size_bytes", 0) / (1024 * 1024)
        print(
            f"{ds['exchange']:<12} {ds['pair']:<15} {ds['resolution']:<12} "
            f"{ds['row_count']:>10,} {start:>12} {end:>12} {size_mb:>8.1f}MB"
        )

    print(f"\n{len(datasets)} dataset(s) found.")


if __name__ == "__main__":
    main()
