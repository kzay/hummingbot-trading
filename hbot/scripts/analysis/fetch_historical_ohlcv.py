"""Fetch historical OHLCV data from Bitget via ccxt.

Downloads up to 6 months of 1-minute BTC-USDT perpetual candles and saves
as Parquet files partitioned by month.

Usage:
    python hbot/scripts/analysis/fetch_historical_ohlcv.py
    python hbot/scripts/analysis/fetch_historical_ohlcv.py --months 3 --output data/historical
    python hbot/scripts/analysis/fetch_historical_ohlcv.py --exchange binance --symbol BTC/USDT:USDT
"""
from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _fetch_ohlcv_ccxt(
    exchange_id: str,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
    limit: int = 1000,
    delay_s: float = 0.3,
) -> list[list]:
    """Fetch OHLCV bars from ccxt in batches. Returns list of [ts_ms, o, h, l, c, v]."""
    try:
        import ccxt  # type: ignore
    except ImportError:
        raise ImportError("ccxt is required: pip install ccxt")

    exchange_cls = getattr(ccxt, exchange_id, None)
    if exchange_cls is None:
        raise ValueError(f"Unknown ccxt exchange: {exchange_id}")

    exchange = exchange_cls({
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })

    all_bars: list[list] = []
    current_since = since_ms

    print(f"Fetching {symbol} {timeframe} from {exchange_id} ...")
    retry_delay = 2.0
    max_retry_delay = 60.0
    while current_since < until_ms:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=current_since, limit=limit)
        except Exception as exc:
            err_str = str(exc).lower()
            if any(p in err_str for p in ("429", "503", "502", "504", "timeout", "rate limit")):
                print(f"  Warning: {exc} — retrying in {retry_delay:.0f}s")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)
                continue
            raise
        retry_delay = 2.0  # reset on success

        if not bars:
            break

        bars = [b for b in bars if b[0] < until_ms]
        all_bars.extend(bars)

        last_ts = bars[-1][0]
        if last_ts <= current_since:
            break
        current_since = last_ts + 1

        print(f"  Fetched {len(all_bars)} bars so far (last: {datetime.fromtimestamp(last_ts / 1000, tz=UTC).isoformat()})  ", end="\r")
        time.sleep(delay_s)

    print(f"\nTotal bars fetched: {len(all_bars)}")
    return all_bars


def _save_parquet(bars: list[list], output_dir: Path, month_tag: str) -> Path:
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        raise ImportError("pandas and pyarrow are required: pip install pandas pyarrow")

    df = pd.DataFrame(bars, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    df = df.drop_duplicates(subset=["timestamp_ms"]).sort_values("timestamp_ms").reset_index(drop=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"bitget_btc_usdt_perp_1m_{month_tag}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Saved {len(df)} bars to {out_path}")
    return out_path


def fetch_months(
    months: int = 6,
    exchange_id: str = "bitget",
    symbol: str = "BTC/USDT:USDT",
    timeframe: str = "1m",
    output_dir: str = "data/historical",
) -> list[Path]:
    now = datetime.now(tz=UTC)
    saved_paths: list[Path] = []
    out = Path(output_dir)

    for m in range(months, 0, -1):
        month_start = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30 * m)).replace(day=1)
        if m == 1:
            month_end = now
        else:
            month_end = (month_start + timedelta(days=32)).replace(day=1)

        month_tag = month_start.strftime("%Y%m")
        out_path = out / f"bitget_btc_usdt_perp_1m_{month_tag}.parquet"
        if out_path.exists():
            print(f"Skipping {month_tag} — already exists at {out_path}")
            saved_paths.append(out_path)
            continue

        since_ms = int(month_start.timestamp() * 1000)
        until_ms = int(month_end.timestamp() * 1000)
        bars = _fetch_ohlcv_ccxt(exchange_id, symbol, timeframe, since_ms, until_ms)
        if bars:
            p = _save_parquet(bars, out, month_tag)
            saved_paths.append(p)

    return saved_paths


def merge_parquets(paths: list[Path], output_path: Path | None = None) -> Path:
    """Merge multiple monthly Parquet files into one."""
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        raise ImportError("pandas is required")

    dfs = [pd.read_parquet(p) for p in paths if p.exists()]
    if not dfs:
        raise ValueError("No Parquet files to merge")

    merged = pd.concat(dfs).drop_duplicates(subset=["timestamp_ms"]).sort_values("timestamp_ms").reset_index(drop=True)
    if output_path is None:
        output_path = paths[0].parent / "bitget_btc_usdt_perp_1m_merged.parquet"
    merged.to_parquet(output_path, index=False)
    print(f"Merged {len(merged)} bars → {output_path}")
    return output_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch historical OHLCV from ccxt")
    ap.add_argument("--months", type=int, default=6, help="Number of months of history to fetch")
    ap.add_argument("--exchange", default="bitget", help="ccxt exchange id")
    ap.add_argument("--symbol", default="BTC/USDT:USDT", help="CCXT symbol")
    ap.add_argument("--timeframe", default="1m")
    ap.add_argument("--output", default="data/historical")
    ap.add_argument("--merge", action="store_true", help="Merge monthly files into one after fetching")
    args = ap.parse_args()

    paths = fetch_months(
        months=args.months,
        exchange_id=args.exchange,
        symbol=args.symbol,
        timeframe=args.timeframe,
        output_dir=args.output,
    )
    if args.merge and paths:
        merge_parquets(paths)
