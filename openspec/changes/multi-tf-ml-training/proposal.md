## Why

The system is hardcoded to 1-minute bars at every layer (PriceBuffer, RegimeDetector inputs, ML Feature Pipeline, ML Feature Event schema, signal consumer). Bot7 — the research/directional bot — runs a trend-pullback strategy on 1m indicators where BB/RSI/ADX produce noise-level signals with stops inside the bid-ask bounce. Meanwhile, the ML training infrastructure (`research.py`) generates labels at 15-minute horizons (`fwd_vol_bucket_15m`, `fwd_return_sign_15m`, `tradability_long_15m`). There is a fundamental mismatch: ML models are trained on 15m targets but no bot can operate on 15m indicators or consume 15m-resolution ML signals. Additionally, no ML models have been trained yet — `lightgbm` is not installed, `data/ml/models` is empty, and ROAD-10/ROAD-11 remain blocked. This change unifies the timeframe architecture and executes the first ML training cycle end-to-end.

## What Changes

- **Resolution-aware PriceBuffer**: PriceBuffer takes `resolution_minutes` at construction time. Internally stores 1m bars in `_1m_store`; a `_indicator_bars` property returns resolution-appropriate bars. ALL indicator methods read from `_indicator_bars` — no per-call parameters, no signature changes. At resolution=1, behavior is identical to today.
- **Per-bot indicator resolution config**: Add `indicator_resolution` field to `SharedMmV24Config` / `DirectionalRuntimeConfig` (default `"1m"` for backward compatibility). Bots declare their operating timeframe.
- **Regime detector multi-TF support**: Replace hardcoded `"1m"` OHLCV fetch in `regime_mixin.py` with the bot's configured `indicator_resolution`.
- **ML Feature Event schema extension**: Add `resolution` field to `MlFeatureEvent` so consumers can filter by timeframe.
- **ML Feature Service multi-resolution publishing**: Publish separate events per configured resolution (`ML_PUBLISH_RESOLUTIONS` env) at appropriate cadences (every N-minute bar close).
- **Signal consumer resolution filter**: `_consume_ml_features` filters events by bot's `indicator_resolution`.
- **Bot7 adaptation to 15m**: Set `indicator_resolution: "15m"` in YAML config. PriceBuffer is constructed at 15m by the kernel — ALL indicator calls in `pullback_v1.py` automatically operate on 15m bars with ZERO code changes. Recalibrate executor parameters (time_limit, grid spacing, barriers) for 15m scale.
- **ML model training**: Install `lightgbm`, run `research.py` pipeline for regime/direction/sizing models on 1-year BTC-USDT historical data, then execute ROAD-10 (regime from combined bot logs) and ROAD-11 (adverse fill classifier from bot5/bot6 fills).
- **Bot7 ML signal wiring**: Enable `ml_features_enabled` and relevant hint flags so bot7 consumes regime/sizing predictions from `hb.ml_features.v1`.

## Capabilities

### New Capabilities

- `multi-resolution-price-buffer`: PriceBuffer takes `resolution_minutes` at construction; `_indicator_bars` property returns resolution-appropriate bars; all indicator methods automatically operate at configured resolution. All existing behavior preserved at 1m default.
- `per-bot-indicator-resolution`: Config-driven indicator timeframe per bot instance. Propagated to regime detection, spread engine inputs, and ML signal consumption.
- `ml-feature-resolution-routing`: MlFeatureEvent includes resolution metadata; ML Feature Service publishes at multiple cadences; signal consumer filters by bot resolution.
- `ml-model-training-pipeline`: End-to-end execution of research.py (regime, direction, sizing) and ROAD-10/ROAD-11 training scripts with walk-forward validation and deployment gates.
- `bot7-15m-adaptation`: Bot7 pullback strategy operates on 15m indicators via config-only change (ZERO code changes to pullback_v1.py), with recalibrated barriers, grid spacing, and ML signal integration.

### Modified Capabilities

- `bot7-configurable-signal-windows`: Signal window parameters (absorption, delta trap) must be recalibrated for 15m bar scale instead of 1m.

## Impact

- **Core runtime** (`controllers/price_buffer.py`, `controllers/runtime/kernel/config.py`, `controllers/runtime/kernel/regime_mixin.py`): Non-breaking additions; default behavior unchanged.
- **Platform contracts** (`platform_lib/contracts/event_schemas.py`): Schema-compatible addition of `resolution` field with default.
- **ML Feature Service** (`services/ml_feature_service/main.py`, `pair_state.py`): New publish cadence logic; existing 1m behavior preserved.
- **Signal consumer** (`simulation/bridge/signal_consumer.py`): Resolution filter added.
- **Bot7** (`data/bot7/conf/controllers/*.yml`): Config parameters recalibrated for 15m. ZERO code changes to `pullback_v1.py` — PriceBuffer handles resolution internally.
- **Dependencies**: `lightgbm` added to ML training requirements.
- **Data**: New model artifacts written to `data/ml/models/`.
- **No breaking changes**: All defaults are 1m; existing bots untouched.
