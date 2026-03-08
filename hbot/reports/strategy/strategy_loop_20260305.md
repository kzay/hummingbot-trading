# Strategy Loop Report (Iteration)

- Generated: `2026-03-05`
- Mode: `ITERATION`
- Bot scope: `bot1` (`BTC-USDT`, paper)
- Data sources: `hbot/data/bot1/logs/epp_v24/bot1_a/minute.csv`, `hbot/data/bot1/logs/epp_v24/bot1_a/fills.csv`, `hbot/reports/strategy/multi_day_summary_latest.json`, `hbot/reports/analysis/performance_dossier_latest.json`

## 1) Baseline scorecard

Current comparison window: `2026-03-01` to `2026-03-05`.

| KPI | Current | Prior baseline | Delta |
|---|---:|---:|---:|
| Fill rate (fills/day) | 384.2 | 101.0 | +283.2 |
| PnL/fill (quote) | -0.0682 | 0.0047 | -0.0729 |
| Maker ratio | 87.19% | 99.80% | -12.61 pp |
| Soft-pause ratio | 37.26% | 49.92% | -12.66 pp |
| Governor size mult avg | 1.0139 | n/a | n/a |

Long window context (`2026-02-14` to `2026-03-05`):
- Total fills: `3993`
- Net PnL: `-95.87`
- Fees: `16.67`
- Max single-day drawdown: `4.31%`
- Spread cap hit ratio: `34.65%`
- Dominant regime: `neutral_low_vol`

## 2) Key findings (ranked)

1. Recent edge quality is negative despite higher activity (`PnL/fill` deteriorated).
2. Inventory/risk stress dominates runtime (`base_pct_above_max` and derisk tags are frequent).
3. Governor is active frequently, but boost is often gated by risk constraints and does not restore positive expectancy.
4. Recent spread competitiveness cap behavior is saturated in the short window.

## 3) Logic / risk / execution issues found

- Regime path includes explicit anti-lookahead behavior by dropping still-forming candles in `hbot/controllers/epp_v2_4.py`.
- Governor size boost can increase notional while strategy is behind target (`hbot/controllers/epp_v2_4.py`).
- Derisk force-taker escalation and runtime recovery paths are active and observable (`hbot/controllers/epp_v2_4.py`).
- Lifecycle and compatibility suites are passing (`hbot/reports/verification/paper_exchange_golden_path_latest.json`, `hbot/reports/verification/paper_exchange_hb_compatibility_latest.json`).

## 4) Paper vs live parity gaps (top 3)

1. `paper_fill_model` was configured as `best_price` in bot config, which is optimistic for PnL realism.
2. Latency is fixed-delay deterministic; this is reproducible but under-represents tail latency shocks.
3. Funding interval modeling exists (8h), but cycle-level funding attribution remains sparse for strategy reporting.

## 5) Improvement proposals (A-D)

- A) Strategy logic
  - Add edge-quality gate before governor size boost activation.
  - Add adaptive spread-cap controller to reduce persistent cap saturation.
- B) Risk controls
  - Tighten `max_base_pct`.
  - Accelerate derisk force-taker activation and reset behavior.
- C) Execution quality
  - Add idempotency key semantics for active adapter retries.
  - Add explicit cancel-before-fill KPI publication.
- D) Config adjustments
  - Move to realistic paper fill profile for validation cycles.
  - Temporarily disable governor size boost during weak-edge diagnosis.

## 6) Next cycle plan (selected changes)

Selected changes:
1. `max_base_pct: 0.60 -> 0.45`
2. `derisk_force_taker_after_s: 90 -> 45`
3. `derisk_progress_reset_ratio: 0.01 -> 0.005`
4. `pnl_governor_max_size_boost_pct: 0.20 -> 0.00`

Experiment design:
- Duration: `>= 5` days or `>= 1500` fills.
- Primary KPIs: `PnL/fill`, `soft_pause_ratio`, `hard_stop_ratio`, `base_pct_above_max` ratio.
- Guardrails: stop early if drawdown `> 4.5%` or hard daily-loss rows become persistent.

## 7) BACKLOG entries (created)

- `[P0-STRAT-20260305-1] Tighten inventory cap for bot1 risk stability`
- `[P1-STRAT-20260305-2] Accelerate derisk force-taker escalation`
- `[P1-STRAT-20260305-3] Run no-size-boost governor experiment`

## 8) Inputs needed next cycle

- Daily cancel-before-fill KPI for bot1.
- Per-regime PnL/fill and maker-taker decomposition.
- Funding accrual expected-vs-applied diagnostics at 8h boundaries.
- Governor size-mult distribution (p50/p90/p99), not only average.

## 9) Assumptions and data gaps

- Prior baseline inferred from `performance_dossier_latest` artifact.
- Minute log coverage in this workspace starts on `2026-03-01`.
- Some long-window metrics come from summary artifacts rather than full minute history.
