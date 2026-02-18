# AI Trend Following V1

This implementation adds an AI-gated directional trend controller for Hummingbot V2:

- Controller: `hbot/controllers/directional_trading/ai_trend_following_v1.py`
- Live config: `hbot/data/bot1/conf/controllers/ai_trend_following_v1_1.yml`
- Paper config: `hbot/data/bot1/conf/controllers/ai_trend_following_v1_paper.yml`
- Script configs:
  - `hbot/data/bot1/conf/scripts/v2_ai_trend_following_v1.yml`
  - `hbot/data/bot1/conf/scripts/v2_ai_trend_following_v1_paper.yml`

## Strategy Logic

### Core indicators

- EMA 50/200 trend filter
- MACD (12,26,9) momentum confirmation
- ADX(14) trend strength gate (`> 25`)
- Supertrend(10,3) directional confirmation
- ATR(14) volatility/risk parameters
- MESA proxy (`MAMA-FAMA`) when available
- Volume oscillator (EMA12/EMA26)

### AI gate

- Uses optional TorchScript LSTM model (`lstm_trend.pt`)
- Entry requires `P(up)` or `P(down)` >= configured threshold (default `0.70`)
- Falls back to deterministic logistic proxy if model artifact is missing

### Risk sizing

- Uses optional scikit-learn RandomForest model (`rf_position_sizer.pkl`)
- Predicts size scalar with clamp bounds (`min_size_scalar`, `max_size_scalar`)
- Falls back to stress-adjusted heuristic when artifact missing

### Risk controls

- Drawdown proxy pause (`max_drawdown_pause_pct`)
- Cost gate (fees/slippage/funding)
- ATR-based SL/TP/trailing barriers
- Script-level max global/controller drawdown controls

## Training Pipeline

Train weekly (local or GitHub Actions):

```bash
python hbot/scripts/analysis/train_ai_trend_following_v1.py \
  --exchange binance \
  --symbol BTC/USDT \
  --timeframe 1h \
  --years 5 \
  --epochs 20 \
  --output-dir hbot/data/models/ai_trend_following_v1
```

## Backtest Utility

```bash
python hbot/scripts/analysis/backtest_ai_trend_following_v1.py \
  --input-csv hbot/scripts/analysis/reports/btcusdt_1h.csv \
  --output-json hbot/scripts/analysis/reports/ai_trend_following_v1_backtest.json \
  --fee-bps 10 \
  --slippage-bps 5 \
  --funding-bps-per-day 4 \
  --threshold 0.70
```

## Run Commands

Paper:

```text
start --script v2_with_controllers.py --conf v2_ai_trend_following_v1_paper.yml
```

Live:

```text
start --script v2_with_controllers.py --conf v2_ai_trend_following_v1.yml
```

## Notes

- This is a production-usable V2 controller architecture with optional ML artifacts.
- For strict microservice separation (dedicated ingestion queue, inference service, and execution gateway), keep this controller as strategy intent layer and move inference/risk scoring to external services over Redis/Kafka queues.
