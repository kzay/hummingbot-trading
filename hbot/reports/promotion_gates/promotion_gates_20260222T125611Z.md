# Promotion Gates Summary

- ts_utc: 2026-02-22T12:56:11.688461+00:00
- status: FAIL
- critical_failures_count: 1
- evidence_bundle_id: 102acda51719eecdafc37aa0efa1dca33c10696c3a65ea773c66d51c74bcb54b

## Critical Failures
- event_store_integrity_freshness

## Checks
- [PASS] preflight_checks: required files present
- [PASS] multi_bot_policy_scope: multi-bot policy scope is consistent across risk/reconciliation/account-map
- [PASS] strategy_catalog_consistency: strategy catalog configs resolve to shared code and declared bundles
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
- F:\Environement\git-repo\hummingbot_custo\hbot\config\strategy_catalog\catalog_v1.json (sha256=2fbce9b3ede5a35e442824f982098e834d34950606521959e007e7f038ef5380)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_a\minute.csv (sha256=bd3e782ec0234a416337966ae43daab4536ddf08ac7b03aa8ce3234d2b77dda9)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_d\minute.csv (sha256=a9be7cdb628f2647c364dfcabb9f0fdff4780721d9dbeced6f5a4b4e793d0dbc)
- F:\Environement\git-repo\hummingbot_custo\hbot\docs\validation\backtest_regression_spec.md (sha256=7fa32faa3844b80a566d3243a69b26ada9be74f8d66776a4fbd045e1b881acd9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=784cf5bbeda52a635e793b79f110d0dabe01f9fd0d9ec193d630861221784dab)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=b75aeff13e96348f0cf688ba25d81a8271734831f66412fffa8de7022c0edcb8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=a87bf09cd34cce96db006c97a06545c7a2fbd7fe46d6a2f519c1c06c16121d72)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=b949615ac4640945db8785f008e596246895e4f68b8ce39f593a30b9f139e232)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=56cf51346afded1d53887cc1848de824a64f611f186e68cf8df16e9b283424d3)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=12a686c4a890e21e971b3511b1c971c5ab9becfbc61d60beebcfb612965553a3)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=78b0102f37b7423229cfaf985be1eebd368d86a650e0124fb07bee851ca379ac)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=4d812d2547cb3538ff396e449eda56ddaf0af2fa22fd6439f9ecef19f4f0d3e6)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\latest.json (sha256=b7de60cded32022e13187f1454f39f2a2fc411055573afc303f00014989a6268)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=74aeac00db156f42f8dd55428af8f31790f1ee4924c64f081d405243c09b2381)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=afb6d49b6c7771631adb473895e3b6e2faac8a190ba07caeed70a483fead6bcb)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_multi_bot_policy.py (sha256=9c7b50f6ae693884964a9cc6234e38b670561e7a10399c04b459e8d651243ddc)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_strategy_catalog_consistency.py (sha256=b3efe7873369592ff0b5747406683765e547f9ce1bb888e66b226c998f1c0d2e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_backtest_regression.py (sha256=b81418c240c277eebd1a685c103a77936d890ec8d763bc0d7412b0c86ca5ea64)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_cycle.py (sha256=c20f4bceef356a572433a936500007247e8a5d74fab6a18727ada4c28244d1cd)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_secrets_hygiene_check.py (sha256=ee612b9c38833b576330d88597dacc8b6bbeb02e8d357ff97d8e384a207e2e9c)
