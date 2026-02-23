# Dashboard KPI Contract v1 (Day 24)

## Purpose
Define the desk performance KPIs shown in Grafana and the source metric for each panel.

## Dashboard
- `monitoring/grafana/dashboards/trading_overview.json`
- Title: `Hummingbot Trading Desk Overview`

## KPI Contract
- `Aggregate Equity (Quote)`
  - Metric: `sum(hbot_bot_equity_quote)`
  - Source: `data/*/logs/epp_v24/*/minute.csv -> equity_quote`
- `Aggregate Daily PnL`
  - Metric: `sum(hbot_bot_daily_pnl_quote)`
  - Source: `daily.csv -> pnl_quote`
- `Max Drawdown %`
  - Metric: `max(hbot_bot_drawdown_pct) * 100`
  - Source: `minute.csv -> drawdown_pct`
- `Rolling 1h Mean Daily PnL`
  - Metric: `avg(avg_over_time(hbot_bot_daily_pnl_quote[1h]))`
  - Source: derived from `hbot_bot_daily_pnl_quote`
- `Equity Curve by Bot`
  - Metric: `hbot_bot_equity_quote`
  - Source: `minute.csv -> equity_quote`
- `Drawdown Curve by Bot`
  - Metric: `hbot_bot_drawdown_pct * 100`
  - Source: `minute.csv -> drawdown_pct`
- `Daily PnL Distribution (Current by Bot)`
  - Metric: `hbot_bot_daily_pnl_quote` (instant)
  - Source: `daily.csv -> pnl_quote`
- `Daily Loss % by Bot`
  - Metric: `hbot_bot_daily_loss_pct * 100`
  - Source: `minute.csv -> daily_loss_pct`
- `Cancel Rate / Min by Bot`
  - Metric: `hbot_bot_cancel_per_min`
  - Source: `minute.csv -> cancel_per_min`
- `Base vs Target Allocation`
  - Metrics:
    - `hbot_bot_base_pct`
    - `hbot_bot_target_base_pct`
  - Source: `minute.csv -> base_pct, target_base_pct`
- `Risk Reasons Info`
  - Metric: `hbot_bot_risk_reasons_info{reasons=*}` (instant table)
  - Source: `minute.csv -> risk_reasons`

## Exported Metrics Added in Day 24
- `hbot_bot_equity_quote`
- `hbot_bot_base_pct`
- `hbot_bot_target_base_pct`
- `hbot_bot_daily_loss_pct`
- `hbot_bot_drawdown_pct`
- `hbot_bot_cancel_per_min`
- `hbot_bot_risk_reasons_info`

## Notes
- `risk_reasons` is exported as an info metric label for operator triage, not for high-cardinality analytics.
- All metrics are scraped via `bot-metrics-exporter` on Prometheus job `bot-metrics`.
