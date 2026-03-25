## 1. PriceBuffer Indicator Additions

- [x] 1.1 Add `macd(fast, slow, signal)` to `PriceBuffer`, computed from the current close series and cached per `_bar_count` + parameter tuple
- [x] 1.2 Add `stoch_rsi(rsi_period, stoch_period, k_smooth, d_smooth)` to `PriceBuffer`, derived from an RSI series with flat-price guard and per-bar caching
- [x] 1.3 Write unit tests for `macd()`: default params, warmup behavior, cache invalidation, all supported resolutions (1m, 5m, 15m, 60m)
- [x] 1.4 Write unit tests for `stoch_rsi()`: default params, warmup, flat-price edge case, resolution compatibility
- [x] 1.5 Verify `py_compile` passes for `price_buffer.py` and run existing PriceBuffer tests to confirm no regressions

## 2. Signal Primitives Library

- [x] 2.1 Create `controllers/backtesting/ta_signals.py` with `SignalResult` frozen dataclass (`direction: Literal["long", "short", "neutral"]`, `strength: float`)
- [x] 2.2 Implement `ema_cross(buf, fast, slow)` signal: detect EMA crossover using previous-bar EMA comparison, return direction and strength
- [x] 2.3 Implement `rsi_zone(buf, period, overbought, oversold)` signal: classify RSI into OB/OS/neutral zones
- [x] 2.4 Implement `macd_cross(buf, fast, slow, signal)` signal: detect MACD histogram sign change
- [x] 2.5 Implement `macd_histogram(buf, fast, slow, signal, threshold)` signal: detect strong histogram momentum
- [x] 2.6 Implement `bb_breakout(buf, period, stddev_mult)` signal: detect close outside Bollinger Bands
- [x] 2.7 Implement `bb_squeeze(buf, period, stddev_mult, squeeze_threshold)` signal: detect narrow bandwidth
- [x] 2.8 Implement `stoch_rsi_cross(buf, rsi_period, stoch_period, k_smooth, d_smooth, overbought, oversold)` signal: detect K/D crossover in extreme zones
- [x] 2.9 Implement `ict_structure(buf, lookback)` signal: wrap ICT library structure detection, feed PriceBuffer bars to ICT state, extract bias
- [x] 2.10 Create `SIGNAL_REGISTRY` plus helper(s) for validating required/optional signal parameters against registered function signatures
- [x] 2.11 Write unit tests for each signal primitive: bullish/bearish/neutral scenarios, warmup edge cases, and strength bounds [0,1]

## 3. ta_composite Config And Warmup Contracts

- [x] 3.1 Create `TaCompositeConfig` (and any nested rule/signal config structures needed) with explicit types for entry rules, exit rules, and position-management fields
- [x] 3.2 Implement config validation: non-empty entry signals, valid signal types, valid signal params, valid rule modes, valid entry order type, non-negative limit offsets, positive SL/TP multipliers
- [x] 3.3 Implement derived warmup calculation from configured indicators plus ATR dependencies, with `min_warmup_bars` acting only as an extra floor
- [x] 3.4 Write unit tests for config validation and warmup derivation, including long-period signals such as `ema_cross(50, 200)`

## 4. ta_composite Adapter

- [x] 4.1 Create `controllers/backtesting/ta_composite_adapter.py` with internal position-state handling that matches `momentum_scalper` behavior but does not refactor existing adapters in v1
- [x] 4.2 Implement `TaCompositeAdapter.warmup()`: feed candle bars into internal `PriceBuffer` and any ICT state needed by configured signals
- [x] 4.3 Implement `tick()` entry logic: evaluate entry rules via `SIGNAL_REGISTRY`, apply `all`/`any`, suppress conflicting OR-mode signals, and submit market or limit entries
- [x] 4.4 Implement `tick()` exit logic: evaluate exit rules with `invert` support, then apply SL/TP/trailing-stop/max-hold/cooldown checks
- [x] 4.5 Implement daily risk gate: track day-open equity, halt new entries when `max_daily_loss_pct` is breached, and reset at the next trading day boundary
- [x] 4.6 Register `ta_composite` in `ADAPTER_REGISTRY`
- [x] 4.7 Write adapter integration tests covering warmup gating, entries, exits, stop-loss, take-profit, trailing stop, cooldown, limit-entry offset, and daily risk halt

## 5. Exploration Prompt Integration

- [x] 5.1 Add `ta_composite` row to the adapter reference table in `exploration_prompts.py` SYSTEM_PROMPT: style="Composable TA", best for, key levers
- [x] 5.2 Add complete `ta_composite` YAML example to `YAML_SCHEMA_REFERENCE` showing entry rules, exit rules, position management, and a note that `min_warmup_bars` is only an additional floor
- [x] 5.3 Add `"ta_composite"` to `SessionConfig.available_adapters` in `exploration_session.py`
- [x] 5.4 Verify `py_compile` on all modified prompt and session files

## 6. Validation

- [x] 6.1 Run OpenSpec validation for `ta-composite-adapter` and fix any artifact issues before coding
- [x] 6.2 Run `py_compile` on all new and modified files
- [x] 6.3 Run targeted pytest suites for the changed modules first, then `PYTHONPATH=hbot python -m pytest hbot/tests/ -x -q --ignore=hbot/tests/integration`
- [x] 6.4 Run architecture contract tests: `PYTHONPATH=hbot python -m pytest hbot/tests/architecture/ -q`
- [x] 6.5 Verify the adapter works end-to-end with a mini backtest config through the harness
