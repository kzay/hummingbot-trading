"""CLI: Download historical market data from exchanges via CCXT.

Usage:
    python -m scripts.backtest.download_data --exchange binance --pair BTC/USDT --resolution 1m --start 2025-01-01 --end 2025-06-01
    python -m scripts.backtest.download_data --exchange bitget --pair BTC/USDT:USDT --resolution trades --start 2025-03-01 --end 2025-03-07
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Download historical data from CCXT exchanges")
    ap.add_argument("--exchange", required=True, help="CCXT exchange id (e.g., binance, bitget)")
    ap.add_argument("--pair", required=True, help="Trading pair (e.g., BTC/USDT, BTC/USDT:USDT)")
    ap.add_argument("--resolution", default="1m", help="Candle resolution (1m, 5m, 15m, 1h, 4h, 1d) or 'trades'")
    ap.add_argument("--start", required=True, help="Start date (ISO format: 2025-01-01)")
    ap.add_argument("--end", required=True, help="End date (ISO format: 2025-06-01)")
    _default_out = os.environ.get("BACKTEST_CATALOG_DIR", "").strip() or "data/historical"
    ap.add_argument(
        "--output",
        default=_default_out,
        help="Output base directory (default: BACKTEST_CATALOG_DIR env or data/historical)",
    )
    args = ap.parse_args()

    from controllers.backtesting.data_catalog import DataCatalog
    from controllers.backtesting.data_downloader import DataDownloader
    from controllers.backtesting.data_store import resolve_data_path, save_candles, save_trades, validate_candles

    since_ms = int(datetime.fromisoformat(args.start).replace(tzinfo=UTC).timestamp() * 1000)
    until_ms = int(datetime.fromisoformat(args.end).replace(tzinfo=UTC).timestamp() * 1000)

    # Normalize pair for path (replace / and : with -)
    pair_path = args.pair.replace("/", "-").replace(":", "-").split("-")
    pair_key = f"{pair_path[0]}-{pair_path[1]}" if len(pair_path) >= 2 else args.pair

    dl = DataDownloader(exchange_id=args.exchange)
    catalog = DataCatalog(base_dir=Path(args.output))

    if args.resolution == "trades":
        print(f"Downloading trades: {args.pair} from {args.exchange} ({args.start} → {args.end})")
        trades = dl.download_trades(args.pair, since_ms, until_ms)
        if not trades:
            print("No trades downloaded.")
            sys.exit(1)
        out_path = resolve_data_path(args.exchange, pair_key, "trades", Path(args.output))
        save_trades(trades, out_path)
        catalog.register(
            exchange=args.exchange, pair=pair_key, resolution="trades",
            start_ms=trades[0].timestamp_ms, end_ms=trades[-1].timestamp_ms,
            row_count=len(trades), file_path=str(out_path),
            file_size_bytes=out_path.stat().st_size,
        )
        print(f"Saved {len(trades)} trades to {out_path}")
    else:
        print(f"Downloading candles: {args.pair} {args.resolution} from {args.exchange} ({args.start} → {args.end})")
        candles = dl.download_candles(args.pair, args.resolution, since_ms, until_ms)
        if not candles:
            print("No candles downloaded.")
            sys.exit(1)
        warnings = validate_candles(candles)
        for w in warnings:
            print(f"  WARNING: {w}")
        out_path = resolve_data_path(args.exchange, pair_key, args.resolution, Path(args.output))
        save_candles(candles, out_path)
        catalog.register(
            exchange=args.exchange, pair=pair_key, resolution=args.resolution,
            start_ms=candles[0].timestamp_ms, end_ms=candles[-1].timestamp_ms,
            row_count=len(candles), file_path=str(out_path),
            file_size_bytes=out_path.stat().st_size,
        )
        print(f"Saved {len(candles)} candles to {out_path}")


if __name__ == "__main__":
    main()
