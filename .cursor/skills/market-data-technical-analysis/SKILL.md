---
name: market-data-technical-analysis
description: Provides guidance for market data pipelines and technical analysis primitives, including candles, indicators, and order book microstructure. Use when the user asks about OHLCV handling, bar construction, indicator computation, order book imbalance/depth signals, feature pipelines, or signal extraction from exchange data.
---

# Market Data Technical Analysis

## Focus

Design signal inputs that are correct, time-aligned, and production-safe.

## When Not to Use

Do not use for portfolio sizing or drawdown policy decisions unless they directly depend on data quality assumptions.

## Core Guidance

- Treat timestamp alignment and clock drift as first-class concerns.
- Define clear bar construction rules (exchange time vs local time).
- Distinguish trade-based features from order book-based features.
- Separate feature generation from strategy decision logic.

## Workflow

1. Define data schema:
   - OHLCV candles, trades, level-2 snapshots, incremental deltas.
2. Validate data quality:
   - missing bars, duplicate events, out-of-order packets.
3. Build indicators:
   - moving averages, volatility measures, momentum, regime filters.
4. Engineer order book features:
   - spread, imbalance, depth slope, short-horizon liquidity shifts.
5. Record feature provenance and recalculation policy.

## Output Template

```markdown
## Data and Signal Spec

- Instruments/timeframes:
- Data sources:
- Candle policy:
- Indicators:
- Order book features:
- Quality checks:
```

## Red Flags

- Mixing different timeframes without synchronization rules.
- Using future data in current-bar features.
- Indicator calculations that silently skip gaps.
- Strategy code directly mutating raw market data.
