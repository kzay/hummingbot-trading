# Promotion Gates Summary

- ts_utc: 2026-02-22T02:10:32.938072+00:00
- status: PASS
- critical_failures_count: 0
- evidence_bundle_id: fc11119b78372059a8cbb6f4a6a6c4e0346505ae1e5c44aee5375b7c29b105ef

## Critical Failures
- none

## Checks
- [PASS] preflight_checks: required files present
- [PASS] smoke_checks: bot4 smoke activity artifacts found
- [PASS] paper_smoke_matrix: bot3 paper-mode intent verified
- [PASS] replay_regression_cycle: replay regression cycle PASS
- [PASS] regression_backtest_harness: regression harness PASS
- [PASS] reconciliation_status: reconciliation healthy and fresh
- [PASS] parity_thresholds: parity pass and fresh
- [PASS] alerting_health: alert webhook evidence is present/recent
- [PASS] event_store_integrity_freshness: event store integrity fresh with zero missing correlations
- [PASS] day2_event_store_gate: day2 gate not yet GO

## Evidence Artifacts
- F:\Environement\git-repo\hummingbot_custo\hbot\config\parity_thresholds.json (sha256=71cb2b0dbf461ba1b88191308b4daaadf2433740aaace9cf8197c9185d7c8224)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\portfolio_limits_v1.json (sha256=551679735ee76f38b80a080e505f11e1ce5420c197932ea56ede316614bc5d7e)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\reconciliation_thresholds.json (sha256=b5498cb7d3b15eee77a21a7cf050837316264286b5504ceb012513073107bbe5)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_a\minute.csv (sha256=bd3e782ec0234a416337966ae43daab4536ddf08ac7b03aa8ce3234d2b77dda9)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_d\minute.csv (sha256=a9be7cdb628f2647c364dfcabb9f0fdff4780721d9dbeced6f5a4b4e793d0dbc)
- F:\Environement\git-repo\hummingbot_custo\hbot\docs\validation\backtest_regression_spec.md (sha256=7fa32faa3844b80a566d3243a69b26ada9be74f8d66776a4fbd045e1b881acd9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=6405ae23407a304e1865a0ebd2d3835ac65599aea6fe67daee3d0aebdede39ce)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=80d9156555bdf94c1cf968df27605596d256b0fe87b6bffa6b4ee7d48b5d29fa)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=d7b0699e225f623c8da6ac1487548fd0b4dcc42c21b7baf6171893daa200761f)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=1fed3492baaa4938ce28fd303a8072e6b06b6bb70a6f102a6c61348493b6ae09)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=4faf7dec1709ca32eb833cc1a035e25209b931c7d78db254b6afc58a2e660402)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=dac36d3311a544a02ca17bb9124fd9970d7143a2f4877b5bd8f643620d935f07)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\latest.json (sha256=6c56a12048c32bc28c7b8330b0fe5acbfa7f0053c631a9142a5c0d0b769c3324)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_backtest_regression.py (sha256=b7c3ccb5887469ea8d28b51a646b340416b9f800ee3ce29f705ddbe762af7898)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_cycle.py (sha256=c20f4bceef356a572433a936500007247e8a5d74fab6a18727ada4c28244d1cd)
