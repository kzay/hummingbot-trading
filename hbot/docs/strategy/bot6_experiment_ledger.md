# Bot6 Experiment Ledger

## Purpose
This ledger is the bot6-specific research trail for controller changes, config experiments, and performance reads.

Use it to:
- keep `bot6` analysis separate from shared `latest` artifacts
- record every bot6 experiment before and after the change
- preserve the evidence bundle used for each decision
- avoid repeating failed bot6 hypotheses

## Bot6 Evidence Bundle
- Runtime config: `hbot/data/bot6/conf/controllers/epp_v2_4_bot6_bitget_cvd_paper.yml`
- Minute log: `hbot/data/bot6/logs/epp_v24/bot6_a/minute.csv`
- Fills log: `hbot/data/bot6/logs/epp_v24/bot6_a/fills.csv`
- Daily state: `hbot/data/bot6/logs/epp_v24/bot6_a/daily_state_bitget_perpetual_paper.json`
- Paper engine state: `hbot/data/bot6/logs/epp_v24/bot6_a/paper_desk_v2.json`
- Desk snapshot: `hbot/reports/desk_snapshot/bot6/latest.json`

## Entry Template
```markdown
## BOT6-EXP-YYYYMMDD-XX: Short title
- Date:
- Type: `config` | `code` | `config+code` | `analysis`
- Hypothesis:
- Changes:
  - `path`: summary
- Observation window:
- Metrics checked:
  - total net pnl:
  - expectancy per fill:
  - maker ratio:
  - drawdown:
- Evidence:
  - `path`
- Result: `keep` | `revert` | `inconclusive`
- Decision / next step:
```

## Baseline
- Controller lane: `bot6_cvd_divergence_v1`
- Pair: `BTC-USDT`
- Mode: `paper`
- Intent: bot6 CVD divergence directional strategy with spot-vs-perp flow signal

## Ledger

## EXP-BOT6-20260317-01: Post-fix viability assessment

**Status**: `proposed`
**Date**: 2026-03-17

**Hypothesis**: CVD spot-vs-perp divergence signal generates positive PnL/fill after denominator fix (P1-STRAT-20260316-3) and baseline fix (P1-STRAT-20260316-4).

**Prerequisites**:
- P1-STRAT-20260316-3 done (CVD denominator fix)
- P1-STRAT-20260316-4 done (delta spike baseline 20 trades)
- P2-STRAT-20260316-8 done (z-score normalization, optional but recommended)
- P2-STRAT-20260316-9 done (spot staleness + trend inference fix)

**Config**: Current bot6 config with z-score window = 100, z-score threshold = 2.0

**Duration**: 48h minimum

**Primary KPIs**:
- Fill count (target: >= 15)
- PnL per fill net of fees (target: > 0)
- Divergence signal hit rate (record)
- Max drawdown (guardrail: < 3%)

**Guardrails**:
- Stop if max DD > 3%
- Stop if bot enters HARD_STOP
- Stop if spot data staleness > 50% of runtime

**Success criteria**: PnL/fill > 0 net of fees with >= 15 fills
**Failure criteria**: PnL/fill < -2 bps or < 5 fills in 48h
**Rollback**: Disable bot6 container
