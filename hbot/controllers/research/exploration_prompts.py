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
like "momentum works" are rejected; precise claims like "BTC-USDT 1m bars \
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
StrategyCandidate schema provided below.

4. **Adapter mode** — Choose an adapter_mode from the available list. \
Each adapter has its own config dataclass and parameter space. Pick the \
one that best matches your hypothesis mechanics.

5. **Parameter space** — Define at least 2 tunable parameters, each with \
3-4 discrete values for grid sweep. Avoid degenerate ranges (e.g., a \
single value or values that collapse the strategy).

6. **Entry/exit logic** — Write as plain-English descriptions referencing \
indicator names and your parameter variable names. The backtest engine \
interprets these.

7. **Base config** — Set data_source fields appropriate for the target \
market. Always include exchange, pair, resolution, instrument_type.

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

### base_config structure:
```yaml
base_config:
  strategy_class: <adapter_mode value>
  strategy_config:
    <adapter-specific params>
  data_source:
    exchange: bitget
    pair: BTC-USDT
    resolution: 1m
    instrument_type: perp
  initial_equity: "500"
  leverage: 1
  seed: 42
  step_interval_s: 60
  warmup_bars: 60
```

### Complete example:
```yaml
name: btc-spike-reversion-v1
hypothesis: >-
  BTC-USDT perpetual shows mean-reverting behavior after large 1m candle
  spikes (>2 ATR). A counter-trend entry with tight stop should capture
  the reversion while limiting adverse selection.
adapter_mode: candle
parameter_space:
  spike_atr_mult: [1.5, 2.0, 2.5, 3.0]
  take_profit_atr: [0.3, 0.5, 0.8]
  stop_loss_atr: [1.0, 1.5, 2.0]
  holding_bars: [3, 5, 10]
entry_logic: >-
  Enter short when close > open + spike_atr_mult * ATR(14).
  Enter long when open > close + spike_atr_mult * ATR(14).
exit_logic: >-
  Close at take_profit_atr * ATR(14) from entry, or
  stop at stop_loss_atr * ATR(14) adverse, or
  time-exit after holding_bars bars.
base_config:
  strategy_class: candle
  strategy_config:
    atr_period: 14
  data_source:
    exchange: bitget
    pair: BTC-USDT
    resolution: 1m
    instrument_type: perp
  initial_equity: "500"
  leverage: 1
  seed: 42
  step_interval_s: 60
  warmup_bars: 60
required_tests:
  - test_adapter_compiles
  - test_no_lookahead_in_entry
metadata:
  author: llm_exploration
  version: "1.0"
lifecycle: candidate
```
"""

GENERATE_PROMPT = """\
Generate a NEW and DIVERSE strategy hypothesis for the following market:

**Market context:**
{market_context}

**Available adapter modes:** {available_adapters}

{rejection_history}\
Produce exactly one YAML block conforming to the StrategyCandidate schema. \
Choose a different market mechanic, indicator set, or time-horizon than any \
previously rejected hypothesis. Be creative but grounded — every claim must \
be testable via backtest.
"""

REVISE_PROMPT = """\
The candidate **{name}** was evaluated and received:

- **Total robustness score:** {score:.3f}
- **Recommendation:** {recommendation}
- **Weakest components:** {weakest_components}

### Score breakdown:
{score_breakdown}

### Report excerpt (first ~100 lines):
```
{report_excerpt}
```

Revise this candidate to specifically address the weakest scoring components \
while preserving any strengths. Produce a complete, updated YAML block. \
You may change parameters, entry/exit logic, or adapter mode if needed, \
but keep the core hypothesis direction if the weakness is execution rather \
than concept. If the concept itself is flawed, propose a substantially \
different hypothesis.
"""
