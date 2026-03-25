## Context

The hbot trading desk runs multiple bots on BTC-USDT perpetual futures (Bitget). Bot1 is a market-making strategy operating on 1m bars. Bot7 is a directional trend-pullback strategy designated as the research bot for ML signal integration. The entire runtime stack — PriceBuffer, RegimeDetector, ML Feature Service, signal consumer — is hardcoded to 1-minute bar resolution. The ML training pipeline (`controllers/ml/research.py`) generates labels at 15-minute horizons but no bot can operate at that timeframe. No ML models have been trained yet (lightgbm not installed, model directory empty).

Key files:
- `controllers/price_buffer.py` — 60s bucket aggregation, hardcoded
- `controllers/runtime/kernel/config.py` — shared config, no resolution field
- `controllers/runtime/kernel/regime_mixin.py` — hardcoded `"1m"` OHLCV fetch
- `services/ml_feature_service/main.py` — publishes per 1m bar, no resolution metadata
- `platform_lib/contracts/event_schemas.py` — `MlFeatureEvent` has no resolution field
- `simulation/bridge/signal_consumer.py` — no timeframe filtering
- `controllers/bots/bot7/pullback_v1.py` — all indicators from 1m `_price_buffer`
- `controllers/ml/research.py` — training pipeline (regime, direction, sizing)

## Goals / Non-Goals

**Goals:**
- Enable any bot to declare its own indicator resolution (1m, 5m, 15m, 1h) via config
- Keep 1m as the base storage resolution in PriceBuffer (highest fidelity)
- Add resampling layer so indicators can be computed on any supported timeframe
- Route ML feature events by resolution so bots only consume matching timeframe signals
- Adapt bot7 from 1m to 15m indicator resolution with recalibrated parameters
- Train ML models (regime, direction, sizing) using the existing research.py pipeline on 1-year historical data
- Execute ROAD-10 (regime classifier from bot logs) and ROAD-11 (adverse fill classifier)
- Wire bot7 to consume ML regime and sizing predictions

**Non-Goals:**
- Changing PriceBuffer's internal storage from 1m (no multi-resolution storage)
- Supporting sub-minute resolutions
- Deploying ML models to production (live trading) — paper validation only
- Hyperparameter optimization with Optuna (future work)
- Multi-pair ML training (BTC-USDT only for now)
- Modifying bot1 or any other bot's timeframe
- Real-time model retraining or online learning

## Decisions

### D1: Resolution-aware PriceBuffer (proper refactor, not per-call patching)

**Decision:** PriceBuffer takes `resolution_minutes` at construction time. Internally stores 1m bars in `_1m_store`. A `_indicator_bars` property returns resolution-appropriate bars (at resolution=1: returns `_1m_store` directly with zero overhead; at resolution>1: returns cached resampled bars). ALL indicator methods read from `_indicator_bars` — no per-call `resolution_minutes` parameter anywhere.

**Rationale:** The per-call approach (`rsi(14, resolution_minutes=15)`) threads a parameter through every indicator call, every strategy method, and every backtest adapter — dozens of call sites to change, each a bug vector. The construction-time approach means the PriceBuffer IS resolution-aware: `bollinger_bands(20, 2)` just works at 15m with zero changes to strategy code. The API is identical; only the internal representation changes.

**Internal design:**
- `_1m_store: deque[MinuteBar]` — always 1m bars, always populated by `add_sample`
- `_indicator_bars` property: at resolution=1 returns `_1m_store` (identical to today); at resolution>1 returns cached resampled list
- `_bar_count` increments per **resolution bar** (not per 1m bar) — all indicator cache keys correct automatically
- `_on_bar_complete` tracks resolution boundaries; clears EMA/ATR caches on boundary (lazy cold start recomputes on next access)
- `bars` public property returns `_indicator_bars`; `bars_1m` public property returns `list(_1m_store)`
- `adverse_drift_30s` uses `_samples` only — completely independent of resolution
- At resolution=1, total behavior is **identical** to today (no regression risk)

**Alternative rejected:** Per-call `resolution_minutes` parameter on every indicator method. Requires changes in pullback_v1.py, backtest adapters, and every strategy that calls indicators. Fragile, verbose, easy to miss a call site.

**Alternative rejected:** Separate PriceBuffer instances per timeframe. Requires dual sampling in tick loop, complicates lifecycle, doubles memory. Unnecessary when 1m bars contain all information for any higher TF.

### D2: Indicator resolution as config field only (no per-call override)

**Decision:** Add `indicator_resolution` to the shared config (default `"1m"`). The kernel passes the resolved `resolution_minutes` to PriceBuffer construction. There is NO per-call parameter.

**Rationale:** With the proper PriceBuffer refactor (D1), per-call overrides are unnecessary. The PriceBuffer knows its resolution and every method just works. If a future strategy needs multi-TF (e.g., 1m for entry timing AND 15m for trend), it can hold a second PriceBuffer instance — this is cleaner than threading per-call parameters. For now, one resolution per bot is sufficient.

### D3: ML Feature Service publish cadence

**Decision:** Publish separate events per resolution at that resolution's bar close. A 15m event is published every 15 minutes when the 15th 1m bar completes. The event's `resolution` field enables consumer filtering.

**Rationale:** Publishing 15m features every 1 minute is wasteful (14 out of 15 events are stale repeats with identical 15m features). Publishing only on bar close matches how bots should consume signals — on new information, not stale repeats.

**Alternative considered:** Publish all resolutions on every 1m bar with a `resolution` field. Rejected: higher Redis throughput with no new information on non-bar-close ticks.

### D4: Regime detection timeframe coupling

**Decision:** Regime detection uses the bot's `indicator_resolution` for OHLCV fetch and ATR/EMA computation. Each bot gets its own regime assessment at its own timeframe.

**Rationale:** A 15m regime and a 1m regime can differ — 1m might show "high_vol_shock" during a 15m "up" trend pullback. Each bot should see the regime at its operating resolution for consistent decision-making.

### D5: Bot7 target timeframe = 15m

**Decision:** 15m for bot7's pullback strategy.

**Rationale:** BB(20) on 15m = 5 hours of price data, capturing real trend structure. ADX on 15m reliably distinguishes trending vs. ranging. ATR-scaled barriers (1.5x/3x at 15m) land at 80-200 bps, well outside noise. Aligns with ML label horizons. 96 bars/day provides enough opportunities. 1m is noise; 1h is too few opportunities for pullback detection.

### D6: ML training order and model selection

**Decision:** Train in this order: (1) regime model from research.py (vol bucket classifier), (2) sizing model (tradability regressor), (3) direction model (skeptical, for research only). Then ROAD-10 (regime from bot logs), then ROAD-11 (adverse fills).

**Rationale:** Regime and sizing models have the strongest theoretical basis (volatility clusters, tradability is regime-aware sizing). Direction prediction at 15m is borderline per ml-trading-guardrails; run it for research value but don't deploy unless feature stability is exceptional. ROAD-10/ROAD-11 come after because they use operational data which has different labeling semantics.

### D7: Combined bot logs for ROAD-10

**Decision:** Combine minute.csv from bot5, bot6, and bot7 (total ~17.7K rows) for ROAD-10 training, since no single bot has the required 10K rows.

**Rationale:** All bots share the same regime detection logic (SharedRuntimeKernel), so regime labels are consistent across bots. The features used (mid, spread, edge, OB imbalance, etc.) are strategy-agnostic microstate columns. Combining provides enough data for 3-window walk-forward CV.

**Risk:** If regime labeling differs subtly between MM and directional bots, model quality may degrade. Mitigation: check regime distribution consistency across bots before combining.

### D8: Regime label mapping for research.py models

**Decision:** Add a `REGIME_CLASS_MAP` in `signal_consumer._consume_ml_features` that maps numeric `fwd_vol_bucket_15m` classes (0=low, 1=normal, 2=elevated, 3=extreme) to regime spec names (`neutral_low_vol`, `neutral_high_vol`, `up`/`down` or `high_vol_shock`).

**Rationale:** `research.py` trains on forward vol bucket labels (integers 0-3). The `signal_consumer` does `str(regime_pred.get("class"))` which produces `"0"`, `"1"`, etc. These do NOT match `_resolved_specs` keys. Without mapping, ML regime overrides silently fail because `set_ml_regime` checks `regime in self._resolved_specs`. ROAD-10 models use string labels (`neutral_low_vol`, etc.) and would work directly.

**Mapping:** `{0: "neutral_low_vol", 1: "neutral_high_vol", 2: "neutral_high_vol", 3: "high_vol_shock"}`. Note: vol buckets don't map to directional regimes (`up`/`down`) because they measure volatility, not trend. High volatility maps to elevated/shock regimes regardless of direction.

**Alternative considered:** Change research.py to output string labels. Rejected: label_generator uses numeric buckets for consistency with percentile-based classification; adding string mapping at consumption is the correct boundary.

### D9: adverse_drift_30s stays sample-based (not bar-based)

**Decision:** `adverse_drift_30s` uses raw price samples (30 seconds of ticks) and is independent of indicator bar timeframe. It SHALL NOT be changed to "30 bars" or "30 × resolution_minutes."

**Rationale:** The drift measures short-horizon adverse price movement for regime shock detection and spread engine input. This is a microstructure signal that should remain high-frequency regardless of whether the bot's indicators operate on 1m or 15m. A 15m-trading bot still needs to detect 30-second price shocks for risk management.

### D10: Dual ML signal path — architectural debt, not addressed now

**Decision:** Document as known technical debt. The `ml_feature_service` → bridge → `set_ml_*` path bypasses `risk_service` and `coordination_service`. The `signal_service` → `ml_signal` → `risk_service` → `coordination_service` path is the governed alternative.

**Rationale:** For paper trading (bot7's role), bypassing risk governance is acceptable — we want direct signal testing without governance delays. Unifying the paths would be a separate architectural change not required for this milestone. The risk governance gap should be addressed before any live deployment.

## Risks / Trade-offs

- **[Risk] Resampled indicator values differ from native higher-TF OHLCV** → Mitigation: Resampling from 1m is mathematically equivalent to native aggregation for OHLCV (no approximation). Indicators computed on resampled bars will match native bars exactly.

- **[Risk] 15m bar has 15x fewer data points → fewer indicator periods in buffer** → Mitigation: PriceBuffer stores up to `price_buffer_bars` (default 200) 1m bars. At 15m resolution, that's ~13 higher-TF bars. For BB(20) we need ≥20 higher-TF bars = 300+ 1m bars in buffer. Config `price_buffer_bars` may need increase for bot7. Document this.

- **[Risk] Direction model passes gates but is overfitting noise** → Mitigation: Per ml-trading-guardrails, direction prediction at <5m is forbidden and 15m is borderline. If direction model passes, require extra scrutiny: check feature stability across all 5 CV windows, verify no single volatile window drives the accuracy. Do not deploy to bot7 without explicit user decision.

- **[Risk] Combined bot logs for ROAD-10 mix different strategy contexts** → Mitigation: Verify regime label distribution is similar across bots before combining. If distributions differ significantly, train per-bot or use only directional bots (bot5/6/7).

- **[Risk] ML feature service increased Redis throughput from multi-resolution publishing** → Mitigation: 15m resolution adds only 1 event per 15 minutes per pair. Negligible compared to existing 1m cadence.

- **[Trade-off] PriceBuffer bars config increase for higher TFs** → Bots using 15m indicators need more 1m bars in buffer (e.g., 400 instead of 200 for BB(20) at 15m). This increases memory slightly (~200 bars × ~50 bytes = ~10KB, negligible).

- **[Risk] Bar-count parameters misaligned at 15m** → Bot7 has parameters that use "bar count" semantics: `pb_basis_slope_bars` (5 bars = 5min at 1m, 75min at 15m), `pb_trend_sma_period` (50 bars = 50min vs 12.5h), `pb_rsi_divergence_lookback` (10 bars = 10min vs 2.5h). Mitigation: Explicitly retune ALL bar-count parameters for 15m scale; document the wall-clock equivalents.

- **[Risk] `pb_signal_max_age_s` expires between 15m bar closes** → Current value (120s) means the execution plan expires 13 out of 15 minutes when signals only update on bar close. Mitigation: Set `pb_signal_max_age_s >= 900` (15-minute bar period) for bot7.

- **[Risk] Regime label mismatch between research.py and signal consumer** → research.py outputs numeric class labels (0-3) that don't match regime spec names. Mitigation: Add label mapping in signal consumer (see D8).

- **[Risk] Sizing hint confidence not gated** → Pre-existing: `set_ml_sizing_hint` in signal_consumer and supervisory_mixin does not apply `ml_confidence_threshold` unlike regime/direction. Acceptable for paper trading; document for future fix.

- **[Risk] Startup seeding insufficient for 15m indicators** → Default `_required_seed_bars()` computes ~25-30 bars (based on 1m periods). BB(20) at 15m needs 300+ 1m bars (5 hours). Mitigation: Update `_required_seed_bars()` to multiply by `_resolution_minutes`. If the exchange API can't provide 300 bars, indicators won't be ready until 5 hours of live running. Seeding from historical parquet (already implemented via data integrity pipeline) provides a fallback.

- **[Risk] EMA/ATR lazy recompute at resolution > 1** → At resolution>1, `_on_bar_complete` clears `_ema_values` and `_atr_values` on each resolution bar boundary. Next `ema()`/`atr()` call triggers lazy cold start from the resampled bars (~26 bars at 15m). This is O(n) per resolution boundary but n is tiny. Recompute happens once per 15 minutes, not per tick. Intentional design choice — incremental updates at resolution level would add complexity for negligible gain.

- **[Risk] Backtest adapter results won't match live bot7 at 15m** → `pullback_adapter.py` and `pullback_adapter_v2.py` use PriceBuffer with 1m assumptions. Without updating these, backtesting would produce 1m results while live bot7 runs at 15m — making strategy validation unreliable. Mitigation: Update adapters to support configurable `indicator_resolution`.

- **[Risk] Signal freshness timeout kills valid signals at 15m** → `_pb_signal_timestamp` only updates when the signal side CHANGES (e.g., off→buy), not on every tick. At 15m, the side may stay "buy" for an entire bar (15 minutes). With the 1m default `pb_signal_max_age_s: 120`, the execution plan would empty after 2 minutes. Mitigation: Set to 960s (slightly over one 15m bar period).

- **[Risk] Docker profiles misconfiguration** → Bot7 requires `--profile test` and ml-feature-service requires `--profile ml`. If either profile is not enabled, the pipeline won't work. Mitigation: Document in docker-compose.yml and bot7 config.

## Migration Plan

1. Multi-TF infrastructure changes are purely additive with 1m defaults — no existing behavior changes.
2. Bot7 config update is a YAML change; old config still works (new fields have defaults).
3. ML model training produces new files in `data/ml/models/` — no existing files modified.
4. ML Feature Service changes are backward-compatible (existing events gain a `resolution: "1m"` default).
5. Rollback: revert bot7 YAML to remove `indicator_resolution` field; delete trained models from `data/ml/models/`.

## Open Questions

None — all design decisions are pre-answered based on codebase analysis and user input.
