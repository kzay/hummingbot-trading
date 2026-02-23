# Day 24 - Performance Analytics v1

## Scope
- Extend `bot-metrics-exporter` with desk-grade risk/performance metrics already present in `minute.csv`.
- Upgrade `Hummingbot Trading Desk Overview` to include equity, drawdown, PnL distribution, and activity/risk posture.

## Implemented
- Exporter extension:
  - `services/bot_metrics_exporter.py`
  - added:
    - `hbot_bot_equity_quote`
    - `hbot_bot_base_pct`
    - `hbot_bot_target_base_pct`
    - `hbot_bot_daily_loss_pct`
    - `hbot_bot_drawdown_pct`
    - `hbot_bot_cancel_per_min`
    - `hbot_bot_risk_reasons_info`
- Dashboard upgrade:
  - `monitoring/grafana/dashboards/trading_overview.json` (version 2)
  - new panels include:
    - aggregate equity
    - aggregate daily pnl
    - drawdown overview and drawdown curve
    - daily pnl distribution snapshot by bot
    - rolling 1h mean pnl
    - base vs target allocation
    - cancel rate and risk reasons table
- KPI contract doc:
  - `docs/ops/dashboard_kpi_contract_v1.md`

## Validation
- `python -m py_compile services/bot_metrics_exporter.py`
- exporter render smoke check confirms new metric names are emitted.
- compose config still valid:
  - `docker compose --env-file env/.env -f compose/docker-compose.yml config`

## Result
- Operators can assess multi-bot PnL, drawdown, risk reasons, and execution activity from Grafana in one pass.
