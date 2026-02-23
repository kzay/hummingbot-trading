# Portfolio Limits v1

## Scope
Portfolio-level controls for Day 5 runtime hardening.

## Policy File
- `config/portfolio_limits_v1.json`

## Active Controls
- **Global daily loss cap**
  - Metric: portfolio-weighted `daily_loss_pct` from bot `minute.csv`.
  - Critical threshold: `global_daily_loss_cap_pct`.
  - Warning threshold: `global_daily_loss_cap_pct * warn_buffer_ratio`.

- **Cross-bot net exposure cap**
  - Metric: absolute portfolio net directional exposure in quote.
  - Formula per bot: `(2 * base_pct - 1) * equity_quote`.
  - Critical threshold: `cross_bot_net_exposure_cap_quote`.
  - Warning threshold: `cross_bot_net_exposure_cap_quote * warn_buffer_ratio`.

- **Concentration cap**
  - Metric: max single-bot equity share in portfolio.
  - Critical threshold: `concentration_cap_pct`.
  - Warning threshold: `concentration_cap_pct * warn_buffer_ratio`.

## Action Mapping
- Any **critical** breach => `kill_switch` action.
- Warning-only breach => `soft_pause` action.
- No breach => `allow`.

## Action Scope
- Risk actions are emitted only for bots in `bot_action_scope`.
- Current intended live scope:
  - `bot1`
  - `bot4`

## Evidence Outputs
- `reports/portfolio_risk/latest.json`
- `reports/portfolio_risk/portfolio_risk_<timestamp>.json`
- `reports/portfolio_risk/audit_<YYYYMMDD>.jsonl`
