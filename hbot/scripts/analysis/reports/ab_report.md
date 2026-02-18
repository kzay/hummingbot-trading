# Strategy A/B Validation Report

- Timestamp (UTC): `2026-02-18T19:16:31.998250+00:00`
- Database: `hbot/scripts/analysis/reports/ab_empty.sqlite`
- Baseline: `directional_max_min_v1`
- Candidate: `systematic_alpha_v2`

## Metrics

| Metric | Baseline | Candidate |
|---|---:|---:|
| rows | 0 | 0 |
| trades | 0 | 0 |
| gross_pnl | 0.0 | 0.0 |
| net_pnl | 0.0 | 0.0 |
| max_drawdown | 0.0 | 0.0 |
| sharpe_proxy | 0.0 | 0.0 |
| profit_factor | 0.0 | 0.0 |
| win_rate | 0.0 | 0.0 |
| turnover | 0.0 | 0.0 |

## Gate Results

| Gate | Pass | Detail |
|---|---|---|
| min_trades | no | baseline=0 candidate=0 min=100 |
| net_pnl_improvement_pct | no | delta=0.00% threshold>=5.0% |
| max_drawdown_increase_pct | yes | increase=0.00% threshold<=0.0% |
| sharpe_delta | yes | delta=0.0000 threshold>=0.0 |
| profit_factor_delta | yes | delta=0.0000 threshold>=0.0 |

## Verdict: FAIL

PASS means candidate satisfies all locked outperform conditions.