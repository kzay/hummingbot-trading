# Strategy Loop — Recurring Strategy Review

**Cadence**: Weekly  
**Mode**: Set MODE below before running

```text
MODE = INITIAL_AUDIT   ← first run: establish baseline, identify all gaps
MODE = ITERATION       ← subsequent runs: compare vs last cycle, track deltas
```

---

```text
You are a quant researcher + execution engineer + risk manager running a recurring
strategy review for a semi-pro BTC-USDT perpetuals market-making desk (EPP v2.4, Bitget, paper).

## System context
- Strategy family: adaptive market-making and directional controllers under `hbot/controllers/`
- Primary controller entrypoints: discover the active strategy controller(s) in `hbot/controllers/` and `hbot/controllers/bots/`
- Shared helpers: spread/risk/regime/logging modules in `hbot/controllers/`
- Strategy configs: `hbot/data/*/conf/controllers/`
- Runtime logs: `hbot/data/*/logs/` including minute/fill CSV artifacts when present
- Strategy reports: `hbot/reports/strategy/`, `hbot/reports/analysis/`, `hbot/reports/verification/`
- Promotion and release checks: `hbot/scripts/release/`
- Scope rule: listed files/folders are anchors, not limits. Inspect any additional relevant paths in the repo.

## Discovery protocol (mandatory)
- Start each review by identifying the active bot ids, config paths, controller entrypoints, and latest report artifacts.
- Treat concrete paths and filenames as examples or anchor patterns, not hard requirements.
- If the repo has moved or renamed a component, use the current equivalent and note the substitution.

## Full config parameter reference (use when reviewing or proposing changes)
| Parameter | Type | Unit | Notes |
|---|---|---|---|
| total_amount_quote | float | USD | Total capital for this bot |
| max_active_executors | int | count | Max simultaneous open orders |
| min_order_amount_quote | float | USD | Floor on single order notional |
| max_order_notional_quote | float | USD | Ceiling on single order notional |
| buy_spreads / sell_spreads | list[float] | fraction (0.001=0.1%) | Per-level spread from mid |
| buy_amounts_pct / sell_amounts_pct | list[float] | fraction of total_amount_quote | Per-level allocation |
| spread_competitiveness_cap_bps | float | bps | Max spread vs best bid/ask; 0=disabled |
| derisk_spread_pct | float | fraction | Spread widening when over inventory target |
| max_base_pct | float | fraction (0.72=72%) | Max base as % of total_amount_quote |
| target_base_pct | float | fraction | Neutral inventory target |
| max_daily_loss_pct | float | fraction | Hard stop drawdown limit |
| max_order_age | float | seconds | Max order age before forced cancel |
| pnl_governor_window | int | minutes | Lookback for governor signal |
| pnl_governor_dampening | float | fraction | Max size reduction (0.3 = min 30% size) |
| pnl_governor_threshold_pct | float | fraction | PnL threshold triggering dampening |
| regime_detector_window | int | candles | Lookback for regime classification |
| chop_spread_mult | float | multiplier | Spread mult in choppy markets |
| trend_spread_mult | float | multiplier | Spread mult in trending markets |

## Inputs I will provide (paste values below)
- MODE: {{INITIAL_AUDIT or ITERATION}}
- Period covered: {{e.g. 2026-02-21 to 2026-02-28}}
- Fill count: {{N}}
- Realized PnL (USD): {{X}}
- Fee spend (USD): {{X}}
- Maker fill ratio (%): {{X}}
- Soft-pause ratio (%): {{X}}  ← time bot spent not quoting
- PnL governor mult avg: {{X}} ← 1.0 = full size, 0.3 = dampened
- Spread competitiveness cap hits (%): {{X}}
- Max drawdown (%): {{X}}
- avg base_pct over period: {{X}}
- Dominant regime (trend/chop/volatile): {{X}}
- Top risk reasons triggering soft-pause: {{list}}
- Config snapshot (current YAML params): {{paste or attach}}
- Last cycle baseline (if MODE=ITERATION): {{paste summary from last run}}

## Data completion protocol (non-blocking)
- If a placeholder can be inferred from repository context, known defaults, or recent reports, fill it.
- If a value is unknown, state `ASSUMPTION:` with a conservative estimate and continue.
- If evidence is missing for a claim, state `DATA_GAP:` and lower confidence accordingly.
- Never stop the review only because some inputs are missing; produce best-effort output.

---

## PHASE 1 — Baseline reconstruction

### If MODE=INITIAL_AUDIT
Establish baseline from provided stats:
- PnL decomposition: gross PnL, fee drag, net PnL, PnL/fill
- Inventory behavior: avg base_pct, drift direction, inventory-driven vs spread-driven PnL
- Activity: fills/day, turnover rate, order-to-fill ratio
- Risk: max drawdown, soft-pause frequency, governor dampening pattern
- Execution: maker ratio, spread capture estimate, cancel-before-fill ratio
- Classify the current edge as: fee-limited / inventory-biased / regime-dependent / churn / healthy

### If MODE=ITERATION
Compare this cycle vs last baseline:
- Delta: PnL/fill, fill rate, soft-pause ratio, governor mult, maker ratio
- What improved, what regressed, what is unchanged
- Did changes from last cycle have the expected effect? (confirm or refute)
- Update the baseline with this cycle's numbers

---

## PHASE 2 — Strategy logic review
(Skip in INITIAL_AUDIT if code has not been read — flag as "needs code review")

### Correctness checks (reference: active controller entrypoint plus supporting helpers)
- Lookahead / repaint risk: are any indicators computed using future data?
- Signal timing: is the signal computed on the same bar it acts on?
- Regime detector (regime_detector.py): does detected regime match observed market behavior this week?
- Spread logic (spread_engine.py): are buy/sell spreads symmetric where they should be?
- Level sizing: do buy_amounts_pct / sell_amounts_pct sum to ≤ 1.0?
- PnL governor (_compute_pnl_governor_size_mult): does it fire at the right threshold? Recover correctly?
- Spread competitiveness cap (_apply_spread_competitiveness_cap): too tight (low fill rate) or too loose (no effect)?
- Derisk logic: when base_pct > max_base_pct, does the bot widen spreads asymmetrically as intended?

### Edge quality
- Is the strategy making money from spread capture or from lucky directional moves?
- Is maker ratio sustainable at current spread settings?
- Does the regime filter improve or hurt overall performance?
- At what market conditions does the strategy lose most? (volatility, trend, illiquidity)

---

## PHASE 3 — Finance and risk review

### PnL correctness
- Is realized PnL calculated correctly (entry price vs exit price, accounting for fees)?
- Are funding payments included in PnL tracking?
- Is paper fill model overstating performance (always mid-fill, no queue position)?

### Risk controls
- Are max_base_pct / max_daily_loss_pct limits being respected?
- Is the kill switch reachable and tested in past 7 days?
- Are stale orders detected and cancelled within max_order_age?
- Is there any orphan position risk after a restart?
- Fee assumptions: are we assuming maker tier correctly?

---

## PHASE 4 — Execution and exchange review

### Order lifecycle
- Is order create → ack → fill → close tracking complete?
- Are partial fills handled correctly in portfolio accounting?
- Is client order ID generation idempotent?
- What is the cancel-before-fill ratio? (high = spreads too tight or order refresh too fast)

### Exchange reliability (Bitget-specific)
- WebSocket reconnect: does the bot recover cleanly after WS drop?
- REST/WS desync: are positions reconciled after reconnect?
- Rate limit headroom: what is current order rate vs Bitget limits?
- Testnet vs mainnet behavior: any known discrepancies affecting paper confidence?

---

## PHASE 5 — Validation and parity review

### Paper vs live gap assessment (reference: paper_engine_v2/)
- Top 3 ways current paper PnL overstates real PnL
- Queue position (matching_engine.py): are we assuming best-in-queue for maker fills?
- Slippage model (fill_models.py): is taker fill at mid realistic? At what spread does this matter?
- Funding (funding_simulator.py): is 8h funding payment modeled correctly for BTC-USDT perps?
- Latency (latency_model.py): does the paper engine account for order placement latency?
- Portfolio accounting (portfolio.py): does realized PnL match what exchange would report?
- Cross-check: compare `hbot/reports/reconciliation/latest.json` vs fill count in the active minute/fill logs

---

## PHASE 6 — Improvement proposals

Group into:
A) Strategy logic fixes (signal, regime, spread, governor)
B) Risk control improvements (limits, kill switch, reconciliation)
C) Execution quality improvements (order lifecycle, fill model, parity)
D) Config parameter adjustments (evidence-based only)

For each proposal:
- Problem (specific, with file or config param reference)
- Root cause
- Proposed change (exact: param value / code location / logic change)
- Expected impact: fill rate / PnL / risk / soft-pause ratio
- Confidence: High / Med / Low (based on evidence quality)
- Effort: S / M / L
- Risk of change: Low / Med / High
- How to validate (what metric changes and in what direction)

---

## PHASE 7 — Next cycle plan

Select 1–3 changes maximum.
Justify: highest expected impact, lowest risk, easiest to validate independently.

For config changes: specify exact param → new value → reason → rollback threshold.
For code changes: specify file → function → what changes.

Define experiment:
- Run duration or min sample (fills, days)
- Primary KPIs to track
- Guardrail KPIs (stop early if these breach)
- Success / failure criteria

---

## PHASE 8 — BACKLOG entries (mandatory)

For every change selected in Phase 7, produce a BACKLOG.md-ready entry:

```markdown
### [P{tier}-STRAT-YYYYMMDD-N] {title} `open`

**Why it matters**: {trading/risk impact in 1-2 sentences}

**What exists now**:
- {file:line or config param} — {current behavior/value}

**Design decision (pre-answered)**: {chosen approach, fully specified}

**Implementation steps**:
1. {exact file + method or YAML param + change}

**Acceptance criteria**:
- {measurable outcome within N days of paper trading}

**Do not**:
- {explicit constraint}
```

Tier: P0 = blocks live/safety · P1 = PnL/reliability · P2 = quality

---

## Output format
1. Baseline scorecard (fill rate / PnL/fill / maker% / soft-pause% / governor avg) + delta vs last cycle
2. Key findings (ranked by trading impact)
3. Logic / risk / execution issues found (with evidence)
4. Paper vs live parity gaps (top 3)
5. Improvement proposals table (grouped A–D, ranked within group)
6. Next cycle plan (1–3 changes, experiment design)
7. BACKLOG entries (copy-paste ready)
8. Inputs needed next cycle (what stats/logs to collect)
9. Assumptions and data gaps (what was inferred vs explicitly provided)

## Rules
- Decisions must be based on evidence from provided stats, not intuition alone
- Never increase position size without positive PnL/fill trend over ≥ 2 cycles
- If governor mult avg < 0.7: investigate strategy edge before changing anything else
- If soft-pause ratio > 30%: fix inventory limits before touching spreads
- Config changes: one parameter group per cycle (sizing OR spreads OR risk — not all)
- Challenge existing strategy assumptions each cycle; keep only what still shows edge.
- Include one bounded creative experiment per cycle with explicit success and rollback criteria.
```
