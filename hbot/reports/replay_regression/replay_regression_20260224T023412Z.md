# Replay Regression Summary

- ts_utc: 2026-02-24T02:34:12.232244+00:00
- status: fail
- deterministic_repeat_pass: True
- repeat_runs: 2

## Blockers
- run_1_snapshot_failures:parity_not_pass
- run_2_snapshot_failures:parity_not_pass

## Evidence Paths
- source_event_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\events_20260222.jsonl
- source_integrity_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json
- frozen_event_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\pinned_inputs\20260224T023352Z\events_20260222.jsonl
- frozen_integrity_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\pinned_inputs\20260224T023352Z\integrity_20260222.json
- frozen_inputs_dir: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\pinned_inputs\20260224T023352Z
- backtest_regression_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json
- reconciliation_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json
- parity_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json
- portfolio_risk_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json
- json_report: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\replay_regression_20260224T023412Z.json
- markdown_report: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\replay_regression_20260224T023412Z.md

## Run Snapshots
- run_1: {"parity_failed_bots": 1, "parity_status": "fail", "portfolio_action": "soft_pause", "portfolio_critical_count": 0, "portfolio_status": "warning", "reconciliation_critical_count": 0, "reconciliation_status": "warning", "reconciliation_warning_count": 3, "regression_event_count": 1058, "regression_fingerprint": "19cdbc865c5159018825712d8da58f700e11bc96f4f13669713b1a371531f1ba", "regression_status": "pass"}
- run_2: {"parity_failed_bots": 1, "parity_status": "fail", "portfolio_action": "soft_pause", "portfolio_critical_count": 0, "portfolio_status": "warning", "reconciliation_critical_count": 0, "reconciliation_status": "warning", "reconciliation_warning_count": 3, "regression_event_count": 1058, "regression_fingerprint": "19cdbc865c5159018825712d8da58f700e11bc96f4f13669713b1a371531f1ba", "regression_status": "pass"}
