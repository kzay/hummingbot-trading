# KPI and Limits

## Purpose
Track acceptance thresholds for promotion between phases and controlled scaling.

## KPI Set
- Net profitability after fees.
- Profit factor.
- Max drawdown.
- Turnover multiple.
- Fee burden (% gross profit).
- Ops incident count (disconnect/reject/balance mismatch).

## Promotion Gates (Phase-0 baseline)
- Turnover `< 3x/day` (ideal `<2x`).
- Profit factor `> 1.25`.
- Max DD `< 3-4%` in validation period.
- No unresolved ops incidents.

## Hard Limits
- Intent target base bounds: `[0.0, 1.0]`.
- ML confidence minimum: `ML_CONFIDENCE_MIN` (default 0.60).
- ML signal age maximum: `ML_MAX_SIGNAL_AGE_MS` (default 3000).
- ML predicted return outlier cap: `RISK_MAX_ABS_PREDICTED_RETURN` (default 0.05).

## Monitoring Sources
- CSV logs under `data/<bot>/logs/epp_v24/...`
- Redis audit/dead-letter streams

## Owner
- Trading/Ops
- Last-updated: 2026-02-19

