## Context

The backtesting harness evaluates strategy candidates proposed by the LLM
exploration agent. Each candidate specifies an `adapter_mode` that maps to a
Python adapter class via `ADAPTER_REGISTRY`. The adapter receives OHLC candles
on each tick and interacts with `PaperDesk` to submit/cancel orders.

Currently, 9 adapters exist. Five are market-making (atr_mm, atr_mm_v2,
smc_mm, combo_mm, simple), two are directional pullback variants, one is a
momentum scalper, and one is a hybrid directional-MM. Each has hard-coded
signal logic — testing a new TA combination requires writing a new Python
adapter.

`PriceBuffer` provides running EMA, SMA, ATR, RSI, ADX, Bollinger Bands, and
stddev. MACD and Stochastic RSI are absent but commonly needed. The ICT
library (`controllers/common/ict/`) provides swing detection, FVG, order
blocks, and structure — already used by `smc_mm`.

## Goals / Non-Goals

**Goals:**
- Let the LLM compose arbitrary TA signal combinations via YAML without
  writing Python code, dramatically expanding the hypothesis search space.
- Add MACD and Stochastic RSI to PriceBuffer so all common TA indicators
  are available from a single object.
- Provide a stateless signal-evaluation layer that can be reused across
  adapters (not just ta_composite).
- Deliver a position-management system (SL/TP/trail) proven by
  momentum_scalper, configurable via YAML.
- Integrate naturally with the existing exploration prompts so the LLM
  discovers ta_composite like any other adapter.

**Non-Goals:**
- Volume-based indicators (VWAP, OBV, MFI) — PriceBuffer stores OHLC only;
  tick-level volume is not available in the 15m candle pipeline. A future
  change can add volume fields.
- Ichimoku Cloud — complex multi-line system with limited alpha in crypto
  perpetuals; defer unless user requests.
- Multi-timeframe signal evaluation — bars at a single resolution per adapter
  invocation. HTF context is handled by existing HTF mechanisms in atr_mm_v2.
- Live-trading adapter — ta_composite is backtesting-only; promotion to live
  requires a separate design.
- ML-based signal weighting or dynamic rule selection.

## Decisions

### D1: Signal primitives as stateless functions

**Decision:** Each signal (ema_cross, rsi_zone, macd_cross, etc.) is a
pure function `(PriceBuffer, config_dict) → SignalResult` with no mutable
state.

**Rationale:** Stateless functions are trivially testable, composable, and
don't interact with each other — the adapter manages all state. Alternative
was a class hierarchy with inheritance; rejected because of unnecessary
complexity for what are essentially one-line evaluations.

**Trade-off:** If a signal needs cross-bar memory (e.g. divergence detection
over N bars), it must compute from the full bar history on each call. At
typical backtest bar counts (<3000), this is fast enough. If profiling shows
issues, we can add optional stateful wrappers later.

### D2: AND/OR rule composition

**Decision:** Entry and exit rules are lists of signal references. Each rule
has a `mode` field: `all` (AND — every signal must agree) or `any` (OR — at
least one signal fires). Nested boolean logic is not supported in v1.

**Rationale:** AND/OR covers >90% of real TA strategies (e.g. "MACD cross AND
RSI not overbought" or "BB breakout OR StochRSI cross"). Nested trees add
YAML complexity that confuses the LLM and is rarely needed. If needed, a
future `nested` mode can be added without breaking existing configs.

### D3: Match momentum_scalper behavior without refactoring it in v1

**Decision:** Implement `ta_composite` position management to match the proven
`momentum_scalper` semantics (SL, TP, trailing stop, max hold, cooldown),
but keep the implementation isolated to `ta_composite` for v1 instead of
extracting shared helpers immediately.

**Rationale:** The behavior is battle-tested, but extracting shared logic now
would enlarge scope and create regression risk in an existing adapter that is
already in use. The safer first step is behavioral parity with targeted tests.
If `ta_composite` proves useful, a follow-up change can extract common helpers
once both adapters' requirements are better understood.

**Alternative considered:** Immediate shared-helper extraction from
`momentum_scalper`. Rejected for v1 because it couples a new feature to an
unrelated refactor and turns an additive change into a cross-adapter change.

### D4: MACD computed on demand from close series with per-bar caching

**Decision:** `PriceBuffer.macd(fast, slow, signal)` returns
`(macd_line, signal_line, histogram)` by computing
`ema(fast) - ema(slow)` for the MACD line, then applying an EMA of period
`signal` over the MACD line series derived from the current close history.
The final tuple is cached per `_bar_count` and parameter set.

**Rationale:** `PriceBuffer` already owns the resampled close series, and the
research/backtest workloads are small enough that recomputing a short MACD
series per completed bar is simpler and less error-prone than introducing
period-specific rolling MACD state. This avoids hidden state bugs and keeps the
indicator implementation deterministic.

### D5: Stochastic RSI is derived from an RSI series, not just the latest RSI

**Decision:** `PriceBuffer.stoch_rsi(rsi_period, stoch_period, k_smooth,
d_smooth)` takes the RSI series, applies a stochastic oscillator
(highest/lowest RSI in `stoch_period`), then smooths K and D with SMA.

**Rationale:** Stoch RSI is a second-order indicator over an RSI time series,
not a transform of the latest RSI point. Computing it from the current close
history per bar is simpler than maintaining extra rolling RSI-only state, and
it stays aligned with the same resampled bar set as the other indicators.

### D6: ICT structure signals via existing library

**Decision:** The `ict_structure` signal primitive wraps
`controllers/common/ict/structure.py` (swing highs/lows, break of structure)
by feeding PriceBuffer bars to the ICT state machine and extracting the
latest structure bias.

**Rationale:** The ICT library already exists and is used by smc_mm. Reusing
it avoids duplication. The signal primitive is a thin adapter that maps
ICT output to `SignalResult`.

### D7: YAML config schema for ta_composite

**Decision:** The `strategy_config` for ta_composite follows this structure:

```yaml
strategy_config:
  adapter_mode: ta_composite
  entry_rules:
    mode: all  # "all" (AND) or "any" (OR)
    signals:
      - type: ema_cross
        fast: 8
        slow: 21
      - type: rsi_zone
        period: 14
        overbought: 70
        oversold: 30
        reject: overbought  # skip buys when OB, skip sells when OS
  exit_rules:
    mode: any
    signals:
      - type: ema_cross
        fast: 8
        slow: 21
        invert: true  # reverse cross = exit
      - type: rsi_zone
        period: 14
        overbought: 75
        oversold: 25
        trigger: extreme  # exit when hitting extreme
  # Position management (reused from momentum_scalper pattern)
  risk_pct: 0.10
  sl_atr_mult: 1.5
  tp_atr_mult: 2.5
  trail_activate_r: 1.0
  trail_offset_atr: 0.8
  max_hold_minutes: 180
  cooldown_s: 300
  atr_period: 14
  max_daily_loss_pct: 0.03
  min_warmup_bars: 60  # optional extra floor; actual warmup is max(derived, configured)
```

**Rationale:** Flat enough for the LLM to generate reliably, expressive
enough for real strategies. Signal types use short, recognizable names.
Each signal's params are adapter-specific kwargs passed to the corresponding
primitive function.

### D9: Warmup is derived from configured indicators

**Decision:** `ta_composite` computes a required warmup bar count from the
configured signals plus ATR/trailing dependencies. `min_warmup_bars` is treated
as an optional user-specified floor, never as a replacement for the derived
minimum.

**Rationale:** A fixed default such as 60 bars is insufficient for slow
configurations like `ema_cross(fast=50, slow=200)` or custom MACD settings.
Deriving warmup from the actual indicator set prevents silent early-bar trading
with uninitialized indicators while keeping the YAML contract simple.

**Alternative considered:** Keep a fixed default warmup only. Rejected because
it creates correctness bugs for longer-period strategies and forces users to
manually reason about indicator internals.

### D8: Prompt changes belong to a prompt capability, not `research-api`

**Decision:** The changes to `exploration_prompts.py` and
`SessionConfig.available_adapters` are captured under a dedicated
`research-exploration-prompts` capability, not under `research-api`.

**Rationale:** `research-api` already refers to HTTP surface area under
`/api/research/*`. The new work changes LLM-facing prompt/schema guidance and
session configuration, not API endpoints. Keeping the capability boundary clean
avoids muddy specs and future confusion during validation.

**Alternative considered:** Reusing `research-api` because the prompt files live
under the research area. Rejected because capability names should follow
behavioral contracts, not folder adjacency.

## Risks / Trade-offs

- **[Combinatorial explosion]** → The LLM could generate nonsensical signal
  combos (e.g. contradictory entry/exit). Mitigation: the adapter validates
  config at construction time and raises `ValueError` for invalid combos;
  the exploration loop catches and rejects these.

- **[Stochastic RSI accuracy at low bar counts]** → StochRSI needs
  `rsi_period + stoch_period + smoothing` bars of warmup. Mitigation:
  `min_warmup_bars` default is set high enough (60); the adapter's `warmup()`
  method validates that enough bars are present before allowing entries.

- **[ICT signal latency]** → ICT structure detection uses swing
  highs/lows which have a confirmation delay. Mitigation: this is inherent
  to the signal; the LLM prompt documents the lag so hypotheses account for
  it.

- **[Position management extraction from momentum_scalper]** → Risk of
  accidental scope creep or behavior drift. Mitigation: keep v1 isolated to
  `ta_composite`; verify parity through targeted tests instead of refactoring
  existing adapters.

- **[Prompt size increase]** → Adding ta_composite documentation to
  exploration_prompts increases token count. Mitigation: keep the table entry
  concise; full YAML examples go in the schema reference section which is
  only included when needed.

## Migration Plan

This is an additive backtesting-only change with no data migration.

- Existing candidate YAML files remain valid because `ta_composite` is a new
  `adapter_mode`, not a replacement.
- Existing adapters remain unchanged in v1; no migration or refactor is
  required to preserve current behavior.
- Rollback is straightforward: remove the registry entry and prompt references
  if the adapter proves unstable.

## Open Questions

- Should v2 support nested boolean groups (`(A and B) or C`) once the flat
  `all`/`any` contract proves stable?
- Do we want signal-level diagnostics in evaluation artifacts so failed
  hypotheses can be understood without replaying a backtest?
