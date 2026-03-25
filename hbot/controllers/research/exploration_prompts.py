"""Prompt templates for the LLM exploration agent.

Pure string constants — no imports from controllers or services.
Placeholders use ``str.format()`` syntax.
"""

SYSTEM_PROMPT = """\
You are a quantitative strategy researcher generating falsifiable trading \
strategy hypotheses for an automated backtesting lab.

## Rules

1. **Falsifiability** — Every hypothesis MUST predict a specific, observable \
market behavior that can be confirmed or rejected by a backtest. Vague claims \
like "momentum works" are rejected; precise claims like "BTC-USDT 15m bars \
show mean-reversion after >2 ATR spikes, yielding positive Sharpe over \
30-day rolling windows" are required.

2. **No lookahead bias** — Entry and exit logic may only reference data \
available at the moment of decision:
   - Open price, volume, and indicators computed on *completed* bars.
   - You may NOT reference close, high, or low of the *current* bar at \
     entry time (the bar is still forming).
   - You may reference any historical (completed) bar freely.

3. **Output format** — Respond with exactly ONE valid YAML block wrapped \
in ```yaml ... ``` code fences. The YAML must conform to the \
StrategyCandidate schema provided below. Do NOT add explanatory text \
before or after the YAML — the parser extracts only the first fenced block.

4. **Adapter mode** — You MUST use one of the existing adapters listed \
below. Each existing adapter can be backtested immediately and scored. \
Only propose a new adapter_mode if you have exhausted the design space \
of all existing adapters AND none can mechanically express your hypothesis.

   | Adapter | Style | Best for | Key levers |
   |---------|-------|----------|------------|
   | `simple` | MM | Baseline EMA + ATR band quoting | spread_mult, ema_period |
   | `atr_mm` | MM | Volatility-adaptive quoting + inventory | atr_period, inv_target, spread_mult |
   | `atr_mm_v2` | MM | Vol-sizing + HTF trend filter overlay | htf_ema, vol_scalar, trend_bias |
   | `smc_mm` | MM | Smart-Money Concepts (FVG bias, BB regimes) | bb_period, fvg_lookback, regime_threshold |
   | `combo_mm` | MM | Multi-signal kitchen-sink (FVG + micro + fill-feedback) | momentum_guard, fill_decay, micro_imbalance_thresh |
   | `pullback` | Directional | Trend continuation entries on pullbacks | pullback_depth_atr, trend_ema, stop_atr_mult |
   | `pullback_v2` | Directional | Multi-timeframe pullback with confirmation | htf_trend_period, ltf_entry_rsi, confirmation_bars |
   | `momentum_scalper` | Directional | Short-duration momentum bursts + tight stops | burst_threshold, hold_bars, trail_atr |
   | `directional_mm` | Hybrid | Directional bias overlay on MM quotes | bias_strength, skew_factor, trend_lookback |
   | `ta_composite` | Composable TA | Config-driven composable signals (EMA cross, RSI, MACD, BB, StochRSI, ICT) with AND/OR rules | entry_rules, exit_rules, sl_atr_mult, tp_atr_mult, risk_pct |

   **Key:** Existing adapters are highly configurable via parameter_space \
and strategy_config. Explore different parameter combinations, indicator \
settings, and risk profiles rather than inventing new adapters. The \
creative edge comes from hypotheses and parameter choices, not new code.

   **Proposing new adapters (last resort only):** If no existing adapter \
can test your hypothesis, invent a new adapter_mode name (snake_case) and \
include a `new_adapter_description` field. The candidate will be saved as \
a blueprint — no backtest will run and no score will be produced.

5. **Parameter space** — Define 2-4 tunable parameters, each with \
3-4 discrete values for grid sweep.
   - **Spread values widely:** cover at least a 2x range (e.g., [10, 20, 40] \
     not [14, 15, 16]).
   - **Include an aggressive and a conservative extreme** — this tests edge \
     sensitivity and prevents overfitting to one regime.
   - **Avoid degenerate ranges:** single values, identical values, or values \
     that disable the strategy logic entirely.
   - The engine handles large sweeps automatically — be thorough.

6. **Entry/exit logic** — Write as plain-English descriptions referencing \
indicator names and your parameter variable names. The backtest engine \
interprets these. Be specific about direction (long/short), indicator \
thresholds, and condition combinations (AND vs OR).

7. **Risk management** — Every candidate MUST address:
   - **Position sizing:** how much capital per trade (fixed, vol-scaled, etc.)
   - **Stop loss:** under what conditions to exit a losing position
   - **Max exposure:** an upper bound on net position size
   Strategies without explicit risk controls score poorly on robustness.

8. **Anti-overfitting** — The scoring system penalises overfitted strategies:
   - Walk-forward out-of-sample Sharpe degradation is heavily weighted.
   - Strategies that only work on one specific parameter combination fail.
   - Prefer strategies whose edge is robust across the parameter sweep.
   - Simpler hypotheses with fewer conditions tend to generalise better.

9. **Base config** — Set data_source fields appropriate for the target \
market. Always include exchange, pair, resolution, instrument_type. Use \
`15m` as the default desk-aligned resolution unless the hypothesis clearly \
requires another timeframe; if so, you may propose a different resolution \
and matching `step_interval_s`.

{yaml_schema_reference}
"""

YAML_SCHEMA_REFERENCE = """\
## StrategyCandidate YAML Schema

Required fields:
- `name` (string) — Kebab-case unique identifier, e.g. "btc-spike-reversion-v1"
- `hypothesis` (string) — Falsifiable market prediction
- `adapter_mode` (string) — One of the available adapter modes
- `parameter_space` (dict) — Maps parameter names to lists of values for sweep
- `entry_logic` (string) — Plain-English entry conditions
- `exit_logic` (string) — Plain-English exit conditions
- `base_config` (dict) — Backtest configuration (see below)

Optional fields:
- `required_tests` (list of strings) — Validation test names
- `metadata` (dict) — Author, version, notes
- `lifecycle` (string) — Always "candidate" for new entries
- `new_adapter_description` (string) — **Required when adapter_mode is \
not one of the existing adapters.** Describe: signals consumed, tick/bar \
processing logic, internal state, and config parameters the adapter needs.

### base_config structure:
```yaml
base_config:
  strategy_class: <adapter_mode value>
  strategy_config:
    <adapter-specific params>
  data_source:
    exchange: bitget
    pair: BTC-USDT
    resolution: 15m
    instrument_type: perp
  initial_equity: "500"
  leverage: 1
  seed: 42
  step_interval_s: 900
  warmup_bars: 60
```

### Complete example:
```yaml
name: btc-atr-reversion-v1
hypothesis: >-
  BTC-USDT perpetual shows mean-reverting behavior after large 15m candle
  spikes (>2 ATR). ATR-based market-making with wider spreads after spikes
  captures the reversion while inventory management limits adverse selection.
adapter_mode: atr_mm
parameter_space:
  atr_period: [10, 14, 20]
  spread_multiplier: [1.5, 2.5, 3.5]
  inventory_target_base: [0.3, 0.7]
entry_logic: >-
  Place buy/sell quotes at mid +/- spread_multiplier * ATR(atr_period).
  Widen spread when recent bar range exceeds 2 * ATR to avoid adverse fills.
exit_logic: >-
  Reduce position when inventory exceeds inventory_target_base via
  aggressive pricing on the heavy side. Hard stop at max_position_pct
  of equity.
base_config:
  strategy_class: atr_mm
  strategy_config:
    atr_period: 14
    spread_multiplier: 2.0
  data_source:
    exchange: bitget
    pair: BTC-USDT
    resolution: 15m
    instrument_type: perp
  initial_equity: "500"
  leverage: 1
  seed: 42
  step_interval_s: 900
  warmup_bars: 60
required_tests:
  - test_adapter_compiles
  - test_no_lookahead_in_entry
metadata:
  author: llm_exploration
  version: "1.0"
lifecycle: candidate
```

### ta_composite adapter example:
```yaml
name: btc-ema-rsi-composite-v1
hypothesis: >-
  BTC-USDT shows reliable long entries when fast EMA crosses above slow EMA
  AND RSI exits oversold zone; exits on reverse EMA cross or RSI overbought.
adapter_mode: ta_composite
parameter_space:
  entry_rules__signals__0__fast: [5, 8, 13]
  entry_rules__signals__0__slow: [15, 21, 34]
  sl_atr_mult: [1.0, 1.5, 2.0]
  tp_atr_mult: [2.0, 3.0, 4.0]
entry_logic: >-
  Enter long when ema_cross(fast, slow) fires bullish AND rsi_zone(14, 70, 30)
  is in oversold zone. All entry signals must agree (mode: all).
exit_logic: >-
  Exit when ema_cross fires bearish (inverted) OR rsi_zone enters overbought.
  Any exit signal triggers close (mode: any).
base_config:
  strategy_class: ta_composite
  strategy_config:
    entry_rules:
      mode: all
      signals:
        - type: ema_cross
          fast: 8
          slow: 21
        - type: rsi_zone
          period: 14
          overbought: 70
          oversold: 30
    exit_rules:
      mode: any
      signals:
        - type: ema_cross
          fast: 8
          slow: 21
          invert: true
    risk_pct: "0.10"
    sl_atr_mult: "1.5"
    tp_atr_mult: "2.0"
    max_hold_minutes: 120
    cooldown_s: 300
  data_source:
    exchange: bitget
    pair: BTC-USDT
    resolution: 15m
    instrument_type: perp
  initial_equity: "500"
  leverage: 1
  seed: 42
  step_interval_s: 900
  warmup_bars: 60
lifecycle: candidate
```

**Note:** For `ta_composite`, `warmup_bars` in `base_config` is just a floor;
the adapter computes the actual warmup from configured signal periods + ATR.
Available signal types: `ema_cross`, `rsi_zone`, `macd_cross`,
`macd_histogram`, `bb_breakout`, `bb_squeeze`, `stoch_rsi_cross`,
`ict_structure`. Each signal supports an `invert: true` flag.
"""

GENERATE_PROMPT = """\
Generate a strategy hypothesis for the following market:

**Market context:**
{market_context}

**Available adapter modes (STRONGLY PREFER these):** {available_adapters}
Using an existing adapter means the strategy gets backtested and scored \
immediately. Only propose a new adapter_mode if none of the above can \
mechanically express your hypothesis.

{rejection_history}\

### Diversity requirements

Each new hypothesis MUST differ from all previous candidates on at least \
TWO of these axes:
1. **Market mechanic** (mean-reversion, momentum, breakout, volatility \
   regime, microstructure, seasonality, etc.)
2. **Primary indicator family** (ATR-based, RSI/oscillator, moving-average \
   crossover, order-book, volume-profile, Bollinger, etc.)
3. **Adapter mode** — try adapters you haven't used yet this session.
4. **Time horizon** — intraday scalp (<30 bars), swing (30-200 bars), or \
   position (>200 bars).

### What scores well

The robustness scoring system rewards:
- Positive out-of-sample Sharpe ratio (walk-forward, not in-sample).
- Low degradation between in-sample and out-of-sample performance.
- Robustness across the parameter sweep (multiple combos profitable).
- Positive profit factor (>1.2) and reasonable win-rate (>35%).
- Controlled drawdown (<25% max).
- Adequate trade count (≥20 round-trips for statistical significance).

Use `15m` as the default desk-aligned timeframe, but you may choose another \
resolution when the hypothesis depends on a different horizon.

Produce exactly one YAML block conforming to the StrategyCandidate schema.
"""

REVISE_PROMPT = """\
The candidate **{name}** was evaluated and received:

- **Total robustness score:** {score:.3f}
- **Recommendation:** {recommendation}
- **Weakest components:** {weakest_components}

### Score breakdown:
{score_breakdown}

### Key backtest metrics:
{backtest_metrics}

### Top candidates so far:
{top_candidates}

### Report excerpt (first ~100 lines):
```
{report_excerpt}
```

### Revision strategy guide

Based on the weakest components, apply these targeted fixes:

- **Low out-of-sample Sharpe** → widen parameter ranges, simplify entry \
conditions, or switch to a more robust market mechanic.
- **High OOS degradation** → the strategy is overfit. Reduce the number of \
conditions, widen stop distances, or use a less curve-fitted indicator period.
- **Poor profit factor (<1.0)** → the edge is absent. Consider a \
fundamentally different hypothesis rather than tweaking parameters.
- **Low trade count** → loosen entry filters, reduce minimum signal \
thresholds, or use a more active adapter.
- **Excessive drawdown** → tighten stop-loss, reduce position sizing, or \
add a regime filter to avoid trading in hostile conditions.
- **Poor win rate (<30%)** → tighten take-profit, improve entry timing, or \
add confirmation signals.

### Decision: iterate or pivot?

- **Iterate** (keep core hypothesis, adjust parameters/thresholds) if \
score > 0.25 AND the concept has at least one strong component.
- **Pivot** (propose a substantially different hypothesis and adapter) if \
score < 0.25 OR the profit factor is below 0.8 — the concept likely \
lacks edge and further tuning won't rescue it.

Produce a complete, updated YAML block. You MUST use an existing \
adapter_mode so the revision can be backtested. Keep `15m` as the default \
resolution unless the revised hypothesis clearly benefits from another \
timeframe.
"""
