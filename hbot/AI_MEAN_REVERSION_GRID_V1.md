# AI Mean Reversion Grid V1

This implementation provides an AI-augmented mean reversion stack for range phases:

- Controller: `hbot/controllers/directional_trading/ai_mean_reversion_grid_v1.py`
- Configs: `hbot/data/bot1/conf/controllers/ai_mean_reversion_grid_v1_*.yml`
- Script launchers: `hbot/data/bot1/conf/scripts/v2_ai_mean_reversion_grid_v1*.yml`
- Model trainer: `hbot/scripts/analysis/train_ai_mean_reversion_gru.py`
- Webhook bridge: `hbot/scripts/utils/grid_webhook_bridge.py`
- Optional CCXT executor: `hbot/scripts/utils/ccxt_grid_executor.py`

## Strategy Logic

- **Entry gates**:
  - Long: RSI < 30, lower Bollinger touch, Z <= -2, ADX range regime, stochastic up-cross.
  - Short: inverse conditions.
  - AI gate: GRU `P(reversion) >= threshold` (default 0.80).
- **Grid**:
  - Dynamic envelope 1-2% around AI expected mean.
  - Dynamic level count 10-20.
  - DCA limit up to 5 levels.
- **Exit**:
  - TP near expected mean.
  - SL at `2 x ATR`.
  - Regime/risk gate disables new entries when ADX breakout regime appears.

## AI/Quant Components

- GRU inference (PyTorch) with fallback heuristic if model is unavailable.
- Features: RSI, BB %B, Z-score, ADX, stochastic K, mean-distance.
- Stationarity gate with ADF test.
- Pair diagnostics with correlation + Engle-Granger cointegration.
- Optional K-Means scan over return vectors for pair diagnostics.

## Risk Controls

- Max leverage cap (`<=2x`).
- Exposure budget cap (default `<=5%` of configured notional).
- AI-driven per-level sizing in `0.2%-0.5%` range.
- Hard gate when stationarity and regime checks fail.

## Webhook + External Grid Routing

The FastAPI bridge forwards normalized grid instructions:

- `POST /grid/3commas`
- `POST /grid/pionex`
- `GET /health`

Required environment variables:

- `THREECOMMAS_WEBHOOK_URL`, `THREECOMMAS_WEBHOOK_TOKEN`
- `PIONEX_WEBHOOK_URL`, `PIONEX_WEBHOOK_TOKEN`

## Deployment Notes

- **Containerization**: package strategy workers and webhook bridge separately.
- **Kubernetes**:
  - `Deployment` for Hummingbot worker.
  - `Deployment` for webhook bridge.
  - `HPA` on CPU/memory for webhook bridge.
- **Observability**:
  - Structured JSON logs for both services.
  - Ship logs to Elasticsearch via Fluent Bit/Vector.
  - Build Kibana dashboards for signal rates, gate rejects, fill health.
- **Alerting**:
  - Alert on elevated gate-fail rate, drawdown, and webhook failures.
  - Include model staleness alarms (missing weekly retrain artifact).

## Training Workflow

1. Export historical OHLCV to CSV.
2. Train:
   - `python hbot/scripts/analysis/train_ai_mean_reversion_gru.py --input-csv <file.csv>`
3. Save model to:
   - `hbot/models/ai_mean_reversion_gru_v1.pt`
4. Point controller config `ai_model_path` to the model artifact.
