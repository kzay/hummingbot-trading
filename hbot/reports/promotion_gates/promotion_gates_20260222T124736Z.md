# Promotion Gates Summary

- ts_utc: 2026-02-22T12:47:36.429152+00:00
- status: FAIL
- critical_failures_count: 1
- evidence_bundle_id: d0833c0c8d6228787a3a285e3372b0a99872e8e0118125aa16263e594b589cff

## Critical Failures
- event_store_integrity_freshness

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
- [PASS] portfolio_risk_status: portfolio risk healthy and fresh
- [PASS] alerting_health: alert webhook evidence is present/recent
- [FAIL] event_store_integrity_freshness: event store integrity missing/stale or missing correlations detected
- [PASS] day2_event_store_gate: day2 gate not yet GO

## Evidence Artifacts
- F:\Environement\git-repo\hummingbot_custo\hbot\config\multi_bot_policy_v1.json (sha256=eddded58c3923cbf14686e297084686d49b74ab0766565adbaeaf1270add35dd)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\parity_thresholds.json (sha256=71cb2b0dbf461ba1b88191308b4daaadf2433740aaace9cf8197c9185d7c8224)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\portfolio_limits_v1.json (sha256=e03aacc170d2a0dec6236846a3614d55316f3a1ee107f660e102f76f546dad03)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\reconciliation_thresholds.json (sha256=5ea94828eb8c5736c66a50d5c3331a87d9a4c14363d680813638dfa1be9519cc)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_a\minute.csv (sha256=bd3e782ec0234a416337966ae43daab4536ddf08ac7b03aa8ce3234d2b77dda9)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_d\minute.csv (sha256=a9be7cdb628f2647c364dfcabb9f0fdff4780721d9dbeced6f5a4b4e793d0dbc)
- F:\Environement\git-repo\hummingbot_custo\hbot\docs\validation\backtest_regression_spec.md (sha256=7fa32faa3844b80a566d3243a69b26ada9be74f8d66776a4fbd045e1b881acd9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=8bce4f645d64676576e3a1f93d5ede13ecf3d1cbd83d53fc4908682091e1fa06)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=b75aeff13e96348f0cf688ba25d81a8271734831f66412fffa8de7022c0edcb8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=a87bf09cd34cce96db006c97a06545c7a2fbd7fe46d6a2f519c1c06c16121d72)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=b949615ac4640945db8785f008e596246895e4f68b8ce39f593a30b9f139e232)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=5dfbe8634d0b1d9830d2d6d4db098be35befc70d084af8408d2b194fcd20b3e7)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=dc95eaa414fbf080c4b63bbb1c0d131764d501a95f2924b38b36bf28fbe319f4)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=8f318e5a936eca1ade43cfb1d852134c5fa71c1e1d4a840319f1d4ba6a16edd3)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=41c7af27cd2688ed566cd63206e641c430f8a2bfb0584b7bd98d500feb966981)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\latest.json (sha256=8a4bd0e0a0988271b936cf6858c3e4bef93bd725c04e5ff28c5703fc4fc04c30)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=3296dc5db29864ee0278dcb4326f704e54dc3b62e98f34940f6f65bdacb490da)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_multi_bot_policy.py (sha256=9c7b50f6ae693884964a9cc6234e38b670561e7a10399c04b459e8d651243ddc)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_backtest_regression.py (sha256=b81418c240c277eebd1a685c103a77936d890ec8d763bc0d7412b0c86ca5ea64)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_cycle.py (sha256=c20f4bceef356a572433a936500007247e8a5d74fab6a18727ada4c28244d1cd)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_secrets_hygiene_check.py (sha256=ee612b9c38833b576330d88597dacc8b6bbeb02e8d357ff97d8e384a207e2e9c)
