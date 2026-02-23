# Multi-Bot Scaling and Isolation Policy v1 (Day 19)

## Purpose
Define explicit bot roles, allowed runtime modes, and safety envelopes so scaling does not silently widen live risk.

## Policy Source of Truth
- `config/multi_bot_policy_v1.json`
- Promotion check: `scripts/release/check_multi_bot_policy.py`

## Bot Role Matrix
- `bot1`
  - Role: `live_microcap_primary`
  - Mode: `live`
  - Exchange: `bitget_perpetual`
  - Allowed symbols: `BTC-USDT`
  - Max notional: `100 USDT`
- `bot2`
  - Role: `reserved_scale_slot`
  - Mode: `disabled`
  - Exchange: `none`
  - Allowed symbols: none
  - Max notional: `0`
- `bot3`
  - Role: `paper_validation`
  - Mode: `paper_only`
  - Exchange: `bitget_paper_trade`
  - Allowed symbols: `BTC-USDT`
  - Max notional: `0` (paper path only)
- `bot4`
  - Role: `connector_validation`
  - Mode: `testnet_probe`
  - Exchange: `binance_perpetual_testnet`
  - Allowed symbols: `BTC-USDT`
  - Max notional: `0` (validation path only)

## Isolation Rules
- Only `bot1` is allowed for live capital.
- Portfolio action scope (`portfolio_limits_v1.json:bot_action_scope`) includes:
  - `bot1` (live primary)
  - `bot4` (testnet validation path, explicitly scope-controlled)
- `bot2` must remain disabled in:
  - `exchange_account_map.json` (`account_mode=disabled`)
  - `reconciliation_thresholds.json` (`bots.bot2.enabled=false`)
- `bot3` must remain paper-only (`account_mode=paper_only`) and is excluded from live portfolio action scope.
- `bot4` is a validation connector bot and must not receive production capital allocation.

## Canonical Runtime Profiles
- Live control plane with primary live bot:
  - `docker compose --env-file ../env/.env --profile external up -d bot1`
- Validation matrix:
  - `docker compose --env-file ../env/.env --profile test up -d bot3 bot4`
- Reserved/disabled scale slot (`bot2`) must not be started in normal operations.

## Change Control Contract
Any change to bot role/mode/scope requires all of:
- Update `config/multi_bot_policy_v1.json`.
- Update related scope files:
  - `config/portfolio_limits_v1.json`
  - `config/exchange_account_map.json`
  - `config/reconciliation_thresholds.json`
- Run:
  - `python scripts/release/check_multi_bot_policy.py`
  - `python scripts/release/run_promotion_gates.py --ci`
- Record evidence in `docs/ops/option4_execution_progress.md`.

## Acceptance Criteria
- Adding a new bot instance cannot widen live risk unless policy + config scope are explicitly edited and the gate runner is re-executed.
