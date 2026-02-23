# Backtest Regression Spec (MVP)

## Purpose
Provide a deterministic regression gate for controller/risk/intent behavior using the Day 2 event-store dataset seed.

## Scope (MVP)
- This is a regression safety harness, not an alpha backtest.
- Uses recorded event data to detect behavioral regressions.

## Inputs
- Event dataset: `reports/event_store/events_<YYYYMMDD>.jsonl`
- Integrity snapshot: `reports/event_store/integrity_<YYYYMMDD>.json`

## Deterministic Checks
1. `event_count_min`
- Pass if event count in dataset is above configured minimum.

2. `missing_correlation_zero`
- Pass if integrity report shows `missing_correlation_count == 0`.

3. `dataset_fingerprint_present`
- Compute a stable SHA256 fingerprint from:
  - total event count
  - first N event ids
  - first N event types
- Pass if fingerprint is generated successfully.

4. `intent_expiry_present_for_active_actions`
- For `execution_intent` actions in `{soft_pause, kill_switch, set_target_base_pct}`, require non-empty `expires_at_ms`.

5. `risk_denied_reason_present`
- For `risk_decision` events where `approved=false`, require non-empty `reason`.

## Outputs
- `reports/backtest_regression/latest.json`
- `reports/backtest_regression/backtest_regression_<timestamp>.json`

## PASS/FAIL Rule
- PASS only if all checks pass.
- FAIL if any check fails.

## Operational Notes
- This MVP can run in `--once` mode locally and in CI-like gate flows.
- Extend later with stronger invariants (no-trade variants, deterministic risk denies, intent expiry checks).
- For deterministic replay checks, pin dataset files explicitly:
  - `python scripts/release/run_backtest_regression.py --event-file <events.jsonl> --integrity-file <integrity.json>`
- Day 10 first-class cycle entrypoint:
  - `python scripts/release/run_replay_regression_cycle.py --repeat 2 --min-events 1000`
# Backtest Regression Spec v1 (Track V)

## Purpose
Provide a **repeatable regression check** that detects changes in controller/risk/intent behavior using **fixed assumptions** and **versioned datasets**.

This is **not** an optimization backtest. It exists to answer:
- “Did behavior change?” and “Did safety invariants regress?”
- “Do we still respect risk/intent contracts under known inputs?”

## Scope (What We Validate)
- Controller preflight and configuration loading (connector/profile correctness).
- Signal → risk decision → execution intent pipeline invariants.
- Intent expiry/idempotency behavior (when applicable).
- “No-trade” variants must place **zero** live orders (paper mode may still emit intents depending on config, but must not result in live placement).
- Fee/slippage assumptions are **explicit and constant** for the regression run.

## Non-Goals
- Predicting real PnL.
- Tuning parameters for higher returns.
- Market-impact modeling / full order-book simulation (can be added later).

## Datasets (Versioned Inputs)
At least one dataset must be versioned and referenced by:
- time window
- connector/venue
- config hash (or a manifest reference)
- schema version

### Dataset A - Event Replay Seed (Preferred)
Source:
- a short “known-good” event window captured during Track R Day 2 (`reports/event_store/` JSONL and accompanying integrity/count snapshot).

Why:
- deterministic event contract validation (counts, schema, correlation ids)
- stable reproduction of reconciliation/parity behavior

### Dataset B - Candle Window (Optional)
Source:
- recorded candles (exchange or local capture), used to validate indicator/signal plumbing and fee/slippage assumptions.

## Assumptions (Must Be Recorded in Output)
- Fees:
  - maker/taker rates used (source: `config/fee_profiles.json` or explicit constants).
- Slippage model:
  - fixed bps (e.g., `expected_slippage_bps`) and/or max tolerated delta.
- Latency budget:
  - fixed per-intent latency or an allowed bound for “staleness”.
- Execution mode:
  - paper vs live; connector testnet/live; and any “no-trade” switch.

## Metrics (Minimal Set)
- **Counts**:
  - events ingested by stream
  - intents produced
  - orders attempted / failed / filled (if available)
- **Invariant checks**:
  - no-trade variants: zero live orders
  - risk denies are deterministic for identical inputs
  - intents past expiry are rejected (or flagged) deterministically
- **Summary**:
  - PASS/FAIL + failure reasons

## Output Contract (Artifacts)
Write artifacts as:
- JSON: machine-readable result used by Day 6 gates
- Markdown: short human-readable summary (what failed, where to look)

Minimum fields in JSON:
- `status`: `pass|fail`
- `dataset_id`: (window + venue + schema)
- `config_ref`: (manifest path or config hash)
- `assumptions`: fees/slippage/latency
- `metrics`: counts + key deltas
- `failures`: list of violated invariants
- `evidence_paths`: pointers to source inputs and logs

## Promotion Gate Integration (Day 6)
Gate policy:
- If controller/strategy/risk code changes: regression backtest is **required**.
- If only infra/ops changes: regression backtest is **recommended** (can be made required once stable).

PASS requirement:
- `status=pass` and zero violated invariants for enabled bots/controllers.

## Future Extensions (Day 8+)
- Add a second dataset window (different volatility regime).
- Add trade-by-trade attribution (still regression-oriented).
- Add order-book or microstructure simulator if needed.

