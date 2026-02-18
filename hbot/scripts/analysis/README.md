# Strategy Validation Toolkit

This directory provides a cost-aware A/B validation workflow for:
- baseline: `directional_max_min_v1`
- candidate: `systematic_alpha_v2`

## Locked Baseline + Gates

Locked in `baseline_lock.yml`:
- baseline/candidate config references
- cost assumptions (fees/slippage/funding)
- pass/fail thresholds

## Usage

1) Extract trades

```bash
python hbot/scripts/analysis/extract_trades.py --db hbot/data/bot1/data/hummingbot.sqlite --strategy-filter directional_max_min_v1 --output hbot/scripts/analysis/reports/baseline_trades.csv
python hbot/scripts/analysis/extract_trades.py --db hbot/data/bot1/data/hummingbot.sqlite --strategy-filter systematic_alpha_v2 --output hbot/scripts/analysis/reports/candidate_trades.csv
```

2) Compute standalone metrics

```bash
python hbot/scripts/analysis/compute_metrics.py --input hbot/scripts/analysis/reports/baseline_trades.csv --output-json hbot/scripts/analysis/reports/baseline_metrics.json
python hbot/scripts/analysis/compute_metrics.py --input hbot/scripts/analysis/reports/candidate_trades.csv --output-json hbot/scripts/analysis/reports/candidate_metrics.json
```

3) Run A/B comparison and verdict

```bash
python hbot/scripts/analysis/compare_strategies.py --db hbot/data/bot1/data/hummingbot.sqlite --lock-config hbot/scripts/analysis/baseline_lock.yml --report-json hbot/scripts/analysis/reports/ab_report.json --report-md hbot/scripts/analysis/reports/ab_report.md
```

## AI Trend Following V1 Utilities

Train PyTorch LSTM trend model + RandomForest sizing model:

```bash
python hbot/scripts/analysis/train_ai_trend_following_v1.py --exchange binance --symbol BTC/USDT --timeframe 1h --years 5 --epochs 20 --output-dir hbot/data/models/ai_trend_following_v1
```

Run quick cost-aware backtest on prepared OHLCV CSV:

```bash
python hbot/scripts/analysis/backtest_ai_trend_following_v1.py --input-csv hbot/scripts/analysis/reports/btcusdt_1h.csv --output-json hbot/scripts/analysis/reports/ai_trend_following_v1_backtest.json --fee-bps 10 --slippage-bps 5 --funding-bps-per-day 4 --threshold 0.70
```
