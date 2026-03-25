## Why

The research lab's 9 existing backtesting adapters are either market-making focused
(atr_mm, smc_mm, combo_mm, directional_mm, simple) or narrowly scoped directional
strategies (pullback, momentum_scalper). There is no general-purpose adapter that
lets the LLM exploration agent compose arbitrary technical-analysis signal
combinations (e.g. "MACD cross + RSI filter + BB breakout") into a testable
directional strategy via YAML config alone.

Today, testing a new TA hypothesis that falls outside the existing adapters'
hard-coded signal logic requires writing a brand-new adapter in Python — a high
friction barrier that defeats the purpose of the automated exploration lab.
A composable signal framework removes that barrier: the LLM proposes signal
rules in YAML, and the engine evaluates them against PriceBuffer indicators
without new code.

## What Changes

- **Add missing indicators to `PriceBuffer`:** MACD (fast/slow/signal EMA line
  and histogram) and Stochastic RSI (smoothed RSI oscillator mapped to 0-100).
  These are the most impactful pure-price indicators absent today.
- **Create a signal primitives library** (`controllers/backtesting/ta_signals.py`):
  stateless functions that evaluate a single TA condition against PriceBuffer
  and return a typed `SignalResult(direction, strength)`. Covers: EMA cross,
  RSI zone, MACD cross, MACD histogram divergence, Bollinger breakout/squeeze,
  Stochastic RSI cross, and ICT structure (via existing `controllers/common/ict/`).
- **Build a `ta_composite` backtesting adapter** that reads a list of signal
  rules from `strategy_config`, evaluates them each bar via the signal library,
  applies configurable AND/OR entry/exit logic, and manages positions with
  ATR-scaled SL/TP and optional trailing stop using the same behavior model as
  `momentum_scalper`, but without refactoring existing adapters in v1.
- **Register `ta_composite` in the adapter registry** and update
  `exploration_prompts.py` so the LLM knows how to use the new adapter.
- **Add unit tests** for the new PriceBuffer indicators, each signal primitive,
  and the composite adapter's entry/exit/position-management logic.

## Capabilities

### New Capabilities
- `ta-signal-primitives`: Stateless signal evaluator library covering EMA cross, RSI zone, MACD cross, MACD histogram, BB breakout/squeeze, Stochastic RSI, and ICT structure signals
- `ta-composite-adapter`: Composable directional backtesting adapter that combines signal primitives via YAML-configured rules with AND/OR logic and ATR-based position management
- `pricebuffer-macd-stochrsi`: MACD and Stochastic RSI indicator additions to PriceBuffer
- `research-exploration-prompts`: LLM prompt and session adapter-list updates so exploration can propose valid `ta_composite` candidates

## Impact

- **Code:** `controllers/price_buffer.py` (new methods), new `controllers/backtesting/ta_signals.py`, new `controllers/backtesting/ta_composite_adapter.py`, modified `controllers/backtesting/adapter_registry.py`, modified `controllers/research/exploration_prompts.py`
- **Tests:** New test files for PriceBuffer indicators, signal primitives, and the composite adapter
- **Dependencies:** None — all indicators are computed from OHLC data already available in PriceBuffer; ICT signals reuse existing `controllers/common/ict/` modules
- **APIs:** No external API changes; the adapter is consumed internally by the backtest harness via the existing `ADAPTER_REGISTRY` mechanism
- **Risk:** Medium-low — additive to the backtest harness, but prompt/schema drift or over-ambitious config semantics could produce invalid exploration candidates if the contract is not kept tight
