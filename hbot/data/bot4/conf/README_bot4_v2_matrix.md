# Bot4 Binance Testnet V2 Matrix

Bot4 is the dedicated validation instance for Binance testnet behavior in V2 controller mode.

## Required one-time setup

1. Container:
   - `docker compose --env-file ../env/.env --profile test up -d --force-recreate bot4`
2. Connector credentials in bot4:
   - `connect binance_perpetual_testnet`

## Scenario matrix

1. Connectivity + execution baseline
   - conf: `v2_epp_v2_4_bot4_binance_smoke.yml`
   - expects: preflight pass, ready transition, controller ticks
2. No-trade safety
   - conf: `v2_epp_v2_4_bot4_binance_notrade.yml`
   - expects: state soft_pause/no active order creation
3. Manual-fee fallback
   - conf: `v2_epp_v2_4_bot4_binance_manual_fee.yml`
   - expects: `fee_source=manual:spot_fee_pct` or manual fallback path
4. Auto-fee resolution
   - conf: `v2_epp_v2_4_bot4_binance_auto_fee.yml`
   - expects: API/runtime fee resolution, no `fee_unresolved`
5. Edge gate pause behavior
   - conf: `v2_epp_v2_4_bot4_binance_edge_pause.yml`
   - expects: soft pause due to edge thresholding
6. Inventory guard behavior
   - conf: `v2_epp_v2_4_bot4_binance_inventory_guard.yml`
   - expects: `risk_reasons` includes inventory guard trigger
7. Cancel-budget throttle
   - conf: `v2_epp_v2_4_bot4_binance_cancel_budget.yml`
   - expects: temporary pause when cancel budget exceeded

## Run command pattern

- `start --script v2_with_controllers.py --conf <scenario_conf>`

## Evidence files

- `logs/logs_v2_epp_v2_4_<scenario>.log`
- `logs/epp_v24/bot4_*/minute.csv`
- `logs/epp_v24/bot4_*/fills.csv`

## Auto evidence snapshot helper

After each scenario run, execute:

- `python /home/hummingbot/custom_scripts/update_matrix_results.py --scenario smoke`
- `python /home/hummingbot/custom_scripts/update_matrix_results.py --scenario notrade`
- `python /home/hummingbot/custom_scripts/update_matrix_results.py --scenario manual_fee`
- `python /home/hummingbot/custom_scripts/update_matrix_results.py --scenario auto_fee`
- `python /home/hummingbot/custom_scripts/update_matrix_results.py --scenario edge_pause`
- `python /home/hummingbot/custom_scripts/update_matrix_results.py --scenario inventory_guard`
- `python /home/hummingbot/custom_scripts/update_matrix_results.py --scenario cancel_budget`

This appends a timestamped snapshot into `conf/bot4_matrix_results.md`.
