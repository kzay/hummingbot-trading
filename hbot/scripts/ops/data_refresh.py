"""Automated data refresh: incremental download, gap repair, materialization.

This script is designed to run as a scheduled job inside the ops-scheduler.
It reads the data requirements manifest to determine scope, downloads
canonical datasets from the exchange, detects/repairs gaps, materializes
higher timeframes from 1m, verifies catalog integrity, and publishes
data catalog events via Redis.

Usage
-----
Direct::

    PYTHONPATH=hbot python scripts/ops/data_refresh.py [--dry-run]

Via ops-scheduler::

    Registered as the ``data-refresh`` job with configurable interval.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger("data_refresh")

# ---------------------------------------------------------------------------
# Timeframe helpers
# ---------------------------------------------------------------------------

_TF_TO_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000,
    "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "8h": 28_800_000, "12h": 43_200_000,
    "1d": 86_400_000,
}

# Canonical datasets that map to exchange endpoints
_CANONICAL_DOWNLOAD_MAP = {
    "1m": "candles",
    "mark_1m": "mark",
    "index_1m": "index",
    "funding": "funding",
    "ls_ratio": "ls_ratio",
}


def _ccxt_symbol(pair: str) -> str:
    """Convert catalog pair 'BTC-USDT' to ccxt symbol 'BTC/USDT:USDT'."""
    parts = pair.split("-")
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}:{parts[1]}"
    return pair


# ---------------------------------------------------------------------------
# Materialization: resample 1m → higher timeframes
# ---------------------------------------------------------------------------


def materialize_higher_timeframes(
    base_dir: Path,
    exchange: str,
    pair: str,
    target_timeframes: list[str],
    dry_run: bool = False,
) -> list[dict]:
    """Resample canonical 1m parquet into higher timeframe parquet files.

    Returns a list of summary dicts for each materialized dataset.
    """
    import pandas as pd
    from controllers.backtesting.data_catalog import DataCatalog
    from controllers.backtesting.data_store import resolve_data_path, save_candles
    from controllers.backtesting.types import CandleRow

    src_path = resolve_data_path(exchange, pair, "1m", base_dir)
    if not src_path.exists():
        logger.warning("Cannot materialize — 1m source missing: %s", src_path)
        return []

    df = pd.read_parquet(src_path)
    if df.empty:
        return []

    df["dt"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    df.set_index("dt", inplace=True)

    catalog = DataCatalog(base_dir)
    results: list[dict] = []

    for tf in target_timeframes:
        interval_ms = _TF_TO_MS.get(tf)
        if interval_ms is None:
            logger.warning("Unknown timeframe %s — skipping materialization", tf)
            continue

        freq_map = {"5m": "5min", "15m": "15min", "1h": "1h", "30m": "30min",
                     "2h": "2h", "4h": "4h", "6h": "6h", "1d": "1D"}
        freq = freq_map.get(tf)
        if freq is None:
            logger.warning("No pandas freq mapping for %s — skipping", tf)
            continue

        if dry_run:
            logger.info("[DRY RUN] Would materialize %s/%s/%s from 1m (%d rows)", exchange, pair, tf, len(df))
            results.append({"exchange": exchange, "pair": pair, "resolution": tf, "row_count": 0, "dry_run": True})
            continue

        resampled = df.resample(freq).agg({
            "timestamp_ms": "first",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["timestamp_ms"])

        resampled["timestamp_ms"] = resampled["timestamp_ms"].astype(int)

        candle_rows = [
            CandleRow(
                timestamp_ms=int(row.timestamp_ms),
                open=Decimal(str(row.open)),
                high=Decimal(str(row.high)),
                low=Decimal(str(row.low)),
                close=Decimal(str(row.close)),
                volume=Decimal(str(row.volume)),
            )
            for row in resampled.itertuples()
        ]

        if not candle_rows:
            continue

        out_path = resolve_data_path(exchange, pair, tf, base_dir)
        save_candles(candle_rows, out_path)
        catalog.register(
            exchange=exchange,
            pair=pair,
            resolution=tf,
            start_ms=candle_rows[0].timestamp_ms,
            end_ms=candle_rows[-1].timestamp_ms,
            row_count=len(candle_rows),
            file_path=str(out_path),
            file_size_bytes=out_path.stat().st_size,
        )
        logger.info("Materialized %s/%s/%s: %d bars", exchange, pair, tf, len(candle_rows))
        results.append({
            "exchange": exchange, "pair": pair, "resolution": tf,
            "row_count": len(candle_rows),
            "start_ms": candle_rows[0].timestamp_ms,
            "end_ms": candle_rows[-1].timestamp_ms,
        })

    return results


# ---------------------------------------------------------------------------
# Gap detection + backfill
# ---------------------------------------------------------------------------


def _detect_and_repair_gaps(
    downloader,
    symbol: str,
    pair: str,
    resolution: str,
    base_dir: Path,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Scan for gaps in a candle parquet and backfill them.

    Returns (gaps_found, gaps_repaired).
    """
    from controllers.backtesting.data_catalog import DataCatalog
    from controllers.backtesting.data_store import (
        load_candles,
        resolve_data_path,
        save_candles,
        scan_gaps,
        validate_candles,
    )

    out_path = resolve_data_path(downloader._exchange_id, pair, resolution, base_dir)
    if not out_path.exists():
        return 0, 0

    candles = load_candles(out_path)
    if not candles:
        return 0, 0

    interval_ms = _TF_TO_MS.get(resolution, 60_000)
    timestamps = [c.timestamp_ms for c in candles]
    gaps = scan_gaps(timestamps, expected_interval_ms=interval_ms)

    if not gaps:
        return 0, 0

    logger.info(
        "Found %d gaps in %s/%s/%s (total missing: %d minutes)",
        len(gaps), downloader._exchange_id, pair, resolution,
        sum((end - start) // 60_000 for start, end in gaps),
    )

    if dry_run:
        return len(gaps), 0

    repaired = 0
    for gap_start, gap_end in gaps:
        try:
            fill = downloader.download_candles(
                symbol, resolution, gap_start, gap_end,
            )
            if fill:
                candles.extend(fill)
                repaired += 1
        except Exception:
            logger.exception(
                "Failed to backfill gap [%d, %d] for %s/%s/%s",
                gap_start, gap_end, downloader._exchange_id, pair, resolution,
            )

    if repaired > 0:
        deduped: dict[int, object] = {c.timestamp_ms: c for c in candles}
        rows = sorted(deduped.values(), key=lambda c: c.timestamp_ms)
        save_candles(rows, out_path)
        catalog = DataCatalog(base_dir)
        catalog.register(
            exchange=downloader._exchange_id,
            pair=pair,
            resolution=resolution,
            start_ms=rows[0].timestamp_ms,
            end_ms=rows[-1].timestamp_ms,
            row_count=len(rows),
            file_path=str(out_path),
            file_size_bytes=out_path.stat().st_size,
        )

    return len(gaps), repaired


# ---------------------------------------------------------------------------
# Main refresh loop
# ---------------------------------------------------------------------------


def refresh(
    *,
    dry_run: bool = False,
    redis_url: str | None = None,
) -> dict:
    """Execute a full data refresh cycle.

    Returns a summary dict of actions taken.
    """
    from controllers.backtesting.data_catalog import DataCatalog
    from controllers.backtesting.data_catalog_events import publish_catalog_update
    from controllers.backtesting.data_downloader import DataDownloader
    from controllers.backtesting.data_requirements import compute_refresh_scope, load_manifest

    manifest = load_manifest()
    scope = compute_refresh_scope(manifest)

    base_dir_env = os.environ.get("BACKTEST_CATALOG_DIR", "").strip()
    base_dir = Path(base_dir_env) if base_dir_env else Path("data/historical")

    exchange = os.environ.get("DATA_REFRESH_EXCHANGE", "").strip() or scope["exchange"]
    pairs = scope["pairs"]
    canonical = scope["canonical_datasets"]
    materialized = scope["materialized_datasets"]

    env_pairs = os.environ.get("DATA_REFRESH_PAIRS", "").strip()
    if env_pairs:
        pairs = [p.strip() for p in env_pairs.split(",") if p.strip()]

    env_datasets = os.environ.get("DATA_REFRESH_DATASETS", "").strip()
    if env_datasets:
        canonical = [d.strip() for d in env_datasets.split(",") if d.strip()]

    now_ms = int(time.time() * 1000)

    redis_client = None
    if not dry_run:
        if not redis_url:
            redis_url = os.environ.get("REDIS_URL", "").strip()
        if not redis_url:
            r_host = os.environ.get("REDIS_HOST", "localhost")
            r_port = os.environ.get("REDIS_PORT", "6379")
            r_db = os.environ.get("REDIS_DB", "0")
            r_pw = os.environ.get("REDIS_PASSWORD", "")
            auth = f":{r_pw}@" if r_pw else ""
            redis_url = f"redis://{auth}{r_host}:{r_port}/{r_db}"
        try:
            import redis
            redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
            redis_client.ping()
        except Exception:
            logger.warning("Could not connect to Redis — catalog events will be skipped")
            redis_client = None

    downloader = DataDownloader(exchange_id=exchange)
    summary: dict = {
        "exchange": exchange,
        "pairs": pairs,
        "canonical_datasets": canonical,
        "materialized_datasets": materialized,
        "dry_run": dry_run,
        "datasets_refreshed": [],
        "gaps_found_total": 0,
        "gaps_repaired_total": 0,
        "materialized_results": [],
        "integrity_warnings": {},
    }

    for pair in pairs:
        symbol = _ccxt_symbol(pair)

        for dataset in canonical:
            kind = _CANONICAL_DOWNLOAD_MAP.get(dataset)
            if kind is None:
                logger.warning("Unknown canonical dataset %s — skipping", dataset)
                continue

            if dry_run:
                logger.info("[DRY RUN] Would refresh %s/%s/%s", exchange, pair, dataset)
                summary["datasets_refreshed"].append(f"{pair}/{dataset}")
                continue

            try:
                if kind == "candles":
                    rows = downloader.download_and_register_candles(
                        symbol, "1m", 0, now_ms,
                        base_dir=base_dir, pair=pair, resume=True,
                    )
                elif kind == "mark":
                    rows = downloader.download_and_register_mark_candles(
                        symbol, "1m", 0, now_ms,
                        base_dir=base_dir, pair=pair, resume=True,
                    )
                elif kind == "index":
                    rows = downloader.download_and_register_index_candles(
                        symbol, "1m", 0, now_ms,
                        base_dir=base_dir, pair=pair, resume=True,
                    )
                elif kind == "funding":
                    rows = downloader.download_and_register_funding(
                        symbol, 0, now_ms,
                        base_dir=base_dir, pair=pair, resume=True,
                    )
                elif kind == "ls_ratio":
                    rows = downloader.download_and_register_long_short_ratio(
                        symbol, "5m", 0, now_ms,
                        base_dir=base_dir, pair=pair, resume=True,
                    )
                else:
                    continue

                summary["datasets_refreshed"].append(f"{pair}/{dataset}")
                logger.info("Refreshed %s/%s/%s: %d rows", exchange, pair, dataset, len(rows) if rows else 0)

            except Exception:
                logger.exception("Failed to refresh %s/%s/%s", exchange, pair, dataset)
                continue

            # Gap detection (only for candle-like datasets)
            if kind in ("candles", "mark", "index"):
                resolution_key = dataset if dataset == "1m" else f"{kind}_{dataset.replace(f'{kind}_', '')}"
                if dataset == "1m":
                    resolution_key = "1m"
                elif dataset == "mark_1m":
                    resolution_key = "mark_1m"
                elif dataset == "index_1m":
                    resolution_key = "index_1m"

                gaps_found, gaps_repaired = _detect_and_repair_gaps(
                    downloader, symbol, pair, resolution_key, base_dir, dry_run=dry_run,
                )
                summary["gaps_found_total"] += gaps_found
                summary["gaps_repaired_total"] += gaps_repaired

            # Publish catalog event
            if redis_client and rows:
                catalog = DataCatalog(base_dir)
                entry = catalog.find(exchange, pair, dataset if dataset == "1m" else dataset)
                if entry:
                    publish_catalog_update(
                        redis_client,
                        exchange=exchange,
                        pair=pair,
                        resolution=entry.get("resolution", dataset),
                        start_ms=entry["start_ms"],
                        end_ms=entry["end_ms"],
                        row_count=entry["row_count"],
                        gaps_found=summary["gaps_found_total"],
                        gaps_repaired=summary["gaps_repaired_total"],
                    )

        # Materialize higher timeframes from 1m
        if materialized:
            mat_results = materialize_higher_timeframes(
                base_dir, exchange, pair, list(materialized), dry_run=dry_run,
            )
            summary["materialized_results"].extend(mat_results)

            # Publish events for materialized datasets
            if redis_client and not dry_run:
                for mat in mat_results:
                    if mat.get("row_count", 0) > 0:
                        publish_catalog_update(
                            redis_client,
                            exchange=exchange,
                            pair=pair,
                            resolution=mat["resolution"],
                            start_ms=mat.get("start_ms", 0),
                            end_ms=mat.get("end_ms", 0),
                            row_count=mat["row_count"],
                        )

    # Integrity check pass
    if not dry_run:
        catalog = DataCatalog(base_dir)
        integrity = catalog.verify_all()
        for key, warnings in integrity.items():
            if warnings:
                for w in warnings:
                    logger.warning("Integrity [%s]: %s", key, w)
        summary["integrity_warnings"] = {k: v for k, v in integrity.items() if v}

        reconciliation = catalog.reconcile_disk()
        if reconciliation["orphans"]:
            logger.warning("Orphan files found: %s", reconciliation["orphans"])
        if reconciliation["stale"]:
            logger.warning("Stale catalog entries found: %d", len(reconciliation["stale"]))

    logger.info("Data refresh complete: %s", json.dumps(summary, default=str))
    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Automated data refresh pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Report what would happen without making changes")
    args = parser.parse_args()

    summary = refresh(dry_run=args.dry_run)

    if args.dry_run:
        print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
