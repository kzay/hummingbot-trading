# Promotion Gates Summary

- ts_utc: 2026-02-22T02:01:13.839912+00:00
- status: FAIL
- critical_failures_count: 1
- evidence_bundle_id: eb41fe1eff42913a4dac4551e4676835579befc198d1f5494e210ad2d0b15fe9

## Critical Failures
- replay_regression_cycle

## Checks
- [PASS] preflight_checks: required files present
- [PASS] smoke_checks: bot4 smoke activity artifacts found
- [PASS] paper_smoke_matrix: bot3 paper-mode intent verified
- [FAIL] replay_regression_cycle: replay regression cycle failed (rc=1)
- [PASS] regression_backtest_harness: regression harness PASS
- [PASS] reconciliation_status: reconciliation healthy and fresh
- [PASS] parity_thresholds: parity pass and fresh
- [PASS] alerting_health: alert webhook evidence is present/recent
- [PASS] event_store_integrity_freshness: event store integrity fresh with zero missing correlations
- [PASS] day2_event_store_gate: day2 gate not yet GO

## Evidence Artifacts
- F:\Environement\git-repo\hummingbot_custo\hbot\config\parity_thresholds.json (sha256=71cb2b0dbf461ba1b88191308b4daaadf2433740aaace9cf8197c9185d7c8224)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\portfolio_limits_v1.json (sha256=842beec058bc9755d3be9248a182bc1fdc8b080ba804c7b9734b5c526d82b2a4)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\reconciliation_thresholds.json (sha256=b5498cb7d3b15eee77a21a7cf050837316264286b5504ceb012513073107bbe5)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_a\minute.csv (sha256=bd3e782ec0234a416337966ae43daab4536ddf08ac7b03aa8ce3234d2b77dda9)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_d\minute.csv (sha256=a9be7cdb628f2647c364dfcabb9f0fdff4780721d9dbeced6f5a4b4e793d0dbc)
- F:\Environement\git-repo\hummingbot_custo\hbot\docs\validation\backtest_regression_spec.md (sha256=7fa32faa3844b80a566d3243a69b26ada9be74f8d66776a4fbd045e1b881acd9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=79ecd0fec8ebc933c2bdd9000470583bb1c5b4ea2e9785d40f6206ebd8412637)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=fb9ddd4f93b5780edcfe67f1e0a471d601f287697d7ec9c9871cf5c973d0270b)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=aa8b89625061b049694c28680a7a2f222a7389d0011819fdc475078373c824b5)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=104e015d18e45e248de7575b4572a7e36508889f5e074319b4c3e682ebb31508)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=d9b1b41619a1af457b24bf65a9c2ac6ea96b08f021f8c57dac137a40a26910c3)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=8e3189973f0a4f9f85b0382975adc395a7f7dd56c1b054cf3f86e0459dde3b84)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\latest.json (sha256=1276311a40d4f278e5efbede8f0ec582219965b075248c0788c073a42800caa7)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_backtest_regression.py (sha256=b7c3ccb5887469ea8d28b51a646b340416b9f800ee3ce29f705ddbe762af7898)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_cycle.py (sha256=c20f4bceef356a572433a936500007247e8a5d74fab6a18727ada4c28244d1cd)
