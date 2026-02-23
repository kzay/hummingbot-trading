# Promotion Gates Summary

- ts_utc: 2026-02-22T02:27:39.246894+00:00
- status: PASS
- critical_failures_count: 0
- evidence_bundle_id: b0fe07c0e78ee0270e618f2b9c92accc460daabab56b47270ef49f8df193847a

## Critical Failures
- none

## Checks
- [PASS] preflight_checks: required files present
- [PASS] multi_bot_policy_scope: multi-bot policy scope is consistent across risk/reconciliation/account-map
- [PASS] secrets_hygiene: no secret leakage markers in docs/reports/log artifacts
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
- F:\Environement\git-repo\hummingbot_custo\hbot\config\multi_bot_policy_v1.json (sha256=eddded58c3923cbf14686e297084686d49b74ab0766565adbaeaf1270add35dd)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\parity_thresholds.json (sha256=71cb2b0dbf461ba1b88191308b4daaadf2433740aaace9cf8197c9185d7c8224)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\portfolio_limits_v1.json (sha256=551679735ee76f38b80a080e505f11e1ce5420c197932ea56ede316614bc5d7e)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\reconciliation_thresholds.json (sha256=b5498cb7d3b15eee77a21a7cf050837316264286b5504ceb012513073107bbe5)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_a\minute.csv (sha256=bd3e782ec0234a416337966ae43daab4536ddf08ac7b03aa8ce3234d2b77dda9)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_d\minute.csv (sha256=a9be7cdb628f2647c364dfcabb9f0fdff4780721d9dbeced6f5a4b4e793d0dbc)
- F:\Environement\git-repo\hummingbot_custo\hbot\docs\validation\backtest_regression_spec.md (sha256=7fa32faa3844b80a566d3243a69b26ada9be74f8d66776a4fbd045e1b881acd9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=9b94062b579a565bc9fc3a7f7b5e905c400f9e1c86d12e58807d611aefdee195)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=82f9366e0e5a76b420704bb4e5788bd5b2ceadffb503ed82396d6914a9866574)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=090558ade1e5980fff7db416a3ab6a35f4e4fa74012f8e7561d2a28dec3c1ef6)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=dbbcd7282e6546338ae6a8522e277ee9727bef4b52240ba5892869b3c35612d8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=b4638a2fcaa2c2c840469d8184406c4c5bc54bf023a2f73eca841129be13c57b)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=1290c796e788f63139437fdeda2d6d74e623aa3cb2da746ccc710ba3e2e0f392)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=618af95ac5489aa207a9c7545ca19925c7643f2f4728318f569136c9fcff0a03)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\latest.json (sha256=111ea58dbe3098e6ddbf941bbf731d8573ac8f253ebe9c5c83d5d8267da9a31c)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=7cd2021b456a3b595c9fee94ad7b4afc7b1ceca48e3277388b70e1650c72cba9)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_multi_bot_policy.py (sha256=9c7b50f6ae693884964a9cc6234e38b670561e7a10399c04b459e8d651243ddc)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_backtest_regression.py (sha256=b7c3ccb5887469ea8d28b51a646b340416b9f800ee3ce29f705ddbe762af7898)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_cycle.py (sha256=c20f4bceef356a572433a936500007247e8a5d74fab6a18727ada4c28244d1cd)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_secrets_hygiene_check.py (sha256=ee612b9c38833b576330d88597dacc8b6bbeb02e8d357ff97d8e384a207e2e9c)
