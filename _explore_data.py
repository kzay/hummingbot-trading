"""Explore available historical data for new edge sources."""
import sys, os, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))
logging.basicConfig(level=logging.WARNING)

import pyarrow.parquet as pq
import pandas as pd

# 1. Funding rates
print("=== FUNDING RATES ===")
fr = pq.read_table("hbot/data/historical/bitget/BTC-USDT/funding/data.parquet").to_pandas()
print(f"Columns: {list(fr.columns)}")
print(f"Shape: {fr.shape}")
print(f"Date range: {fr.iloc[0]} to {fr.iloc[-1]}")
print(fr.head(10).to_string())
print(f"\nFunding rate stats:")
if 'rate' in fr.columns:
    print(fr['rate'].describe())
elif 'funding_rate' in fr.columns:
    print(fr['funding_rate'].describe())
else:
    print("Cols:", fr.columns.tolist())

# 2. Candle data quality check
print("\n\n=== CANDLE DATA ===")
candles = pq.read_table("hbot/data/historical/bitget/BTC-USDT/1m/data.parquet").to_pandas()
print(f"Columns: {list(candles.columns)}")
print(f"Shape: {candles.shape}")
print(f"First row:\n{candles.iloc[0]}")
print(f"Last row:\n{candles.iloc[-1]}")

# Check for gaps
if 'timestamp_ms' in candles.columns:
    diffs = candles['timestamp_ms'].diff().dropna()
    expected_diff = 60000  # 1m
    gaps = diffs[diffs != expected_diff]
    print(f"\nTimestamp diffs: expected {expected_diff}ms")
    print(f"Total bars: {len(candles)}")
    print(f"Bars with unexpected gap: {len(gaps)}")
    if len(gaps) > 0:
        print(f"Gap distribution:")
        print(gaps.value_counts().head(10))

# Check candle price volatility distribution
if 'high' in candles.columns and 'low' in candles.columns and 'close' in candles.columns:
    candles['range_pct'] = (candles['high'] - candles['low']) / candles['close'] * 100
    candles['return_pct'] = candles['close'].pct_change() * 100
    print(f"\n1m range (%) stats:")
    print(candles['range_pct'].describe())
    print(f"\n1m return (%) stats:")
    print(candles['return_pct'].describe())

# 3. Trades data
print("\n\n=== TRADES DATA ===")
trades = pq.read_table("hbot/data/historical/bitget/BTC-USDT/trades/data.parquet").to_pandas()
print(f"Columns: {list(trades.columns)}")
print(f"Shape: {trades.shape}")
print(trades.head(5).to_string())

print("\n\nDone!")
