# Replay Regression Summary

- ts_utc: 2026-02-22T01:17:30.788565+00:00
- status: fail
- deterministic_repeat_pass: True
- repeat_runs: 2

## Blockers
- run_1_step_failures:backtest_regression
- run_1_snapshot_failures:regression_not_pass
- run_2_step_failures:backtest_regression
- run_2_snapshot_failures:regression_not_pass

## Evidence Paths
- source_event_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\events_20260222.jsonl
- source_integrity_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json
- frozen_event_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\pinned_inputs\20260222T011729Z\events_20260222.jsonl
- frozen_integrity_file: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\pinned_inputs\20260222T011729Z\integrity_20260222.json
- frozen_inputs_dir: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\pinned_inputs\20260222T011729Z
- backtest_regression_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json
- reconciliation_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json
- parity_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json
- portfolio_risk_latest: F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json
- json_report: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\replay_regression_20260222T011730Z.json
- markdown_report: F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\replay_regression_20260222T011730Z.md

## Run Snapshots
- run_1: {"parity_failed_bots": 0, "parity_status": "pass", "portfolio_action": "allow", "portfolio_critical_count": 0, "portfolio_status": "ok", "reconciliation_critical_count": 0, "reconciliation_status": "ok", "reconciliation_warning_count": 0, "regression_event_count": 238, "regression_fingerprint": "0aff3d856eb930cea19916939f4801aa9f0a2f714812f8bf1efb056e8ae324ec", "regression_status": "fail"}
- run_2: {"parity_failed_bots": 0, "parity_status": "pass", "portfolio_action": "allow", "portfolio_critical_count": 0, "portfolio_status": "ok", "reconciliation_critical_count": 0, "reconciliation_status": "ok", "reconciliation_warning_count": 0, "regression_event_count": 238, "regression_fingerprint": "0aff3d856eb930cea19916939f4801aa9f0a2f714812f8bf1efb056e8ae324ec", "regression_status": "fail"}
