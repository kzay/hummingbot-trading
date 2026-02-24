# Replay Regression Summary

- ts_utc: 2026-02-24T02:34:53.347799+00:00
- status: fail
- deterministic_repeat_pass: True
- repeat_runs: 2

## Blockers
- run_1_snapshot_failures:parity_not_pass
- run_2_snapshot_failures:parity_not_pass

## Evidence Paths
- source_event_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\events_20260221.jsonl
- source_integrity_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260221.json
- frozen_event_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\pinned_inputs\20260224T023432Z\events_20260221.jsonl
- frozen_integrity_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\pinned_inputs\20260224T023432Z\integrity_20260221.json
- frozen_inputs_dir: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\pinned_inputs\20260224T023432Z
- backtest_regression_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json
- reconciliation_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json
- parity_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json
- portfolio_risk_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json
- json_report: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\replay_regression_20260224T023453Z.json
- markdown_report: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\replay_regression_20260224T023453Z.md

## Run Snapshots
- run_1: {"parity_failed_bots": 1, "parity_status": "fail", "portfolio_action": "soft_pause", "portfolio_critical_count": 0, "portfolio_status": "warning", "reconciliation_critical_count": 0, "reconciliation_status": "warning", "reconciliation_warning_count": 3, "regression_event_count": 87885, "regression_fingerprint": "f1c9fe78d84f8e8e22bcaccff936a1dcf0fc441fafdab52c3f708ddb53186285", "regression_status": "pass"}
- run_2: {"parity_failed_bots": 1, "parity_status": "fail", "portfolio_action": "soft_pause", "portfolio_critical_count": 0, "portfolio_status": "warning", "reconciliation_critical_count": 0, "reconciliation_status": "warning", "reconciliation_warning_count": 3, "regression_event_count": 87885, "regression_fingerprint": "f1c9fe78d84f8e8e22bcaccff936a1dcf0fc441fafdab52c3f708ddb53186285", "regression_status": "pass"}
