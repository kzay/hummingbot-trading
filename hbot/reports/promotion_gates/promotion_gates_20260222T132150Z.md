# Promotion Gates Summary

- ts_utc: 2026-02-22T13:21:50.993994+00:00
- status: FAIL
- critical_failures_count: 2
- evidence_bundle_id: f9486f7404cddd1150c85733219b7f837f83ed041936463a329075d38e4fb310

## Critical Failures
- unit_service_integration_tests
- day2_event_store_gate

## Checks
- [PASS] preflight_checks: required files present
- [PASS] multi_bot_policy_scope: multi-bot policy scope is consistent across risk/reconciliation/account-map
- [PASS] strategy_catalog_consistency: strategy catalog configs resolve to shared code and declared bundles
- [PASS] coordination_policy_scope: coordination service runs only in policy-permitted scope/mode
- [FAIL] unit_service_integration_tests: deterministic tests failed (rc=2)
- [PASS] secrets_hygiene: no secret leakage markers in docs/reports/log artifacts
- [PASS] smoke_checks: bot4 smoke activity artifacts found
- [PASS] paper_smoke_matrix: bot3 paper-mode intent verified
- [PASS] replay_regression_cycle: replay regression cycle PASS
- [PASS] regression_backtest_harness: regression harness PASS
- [PASS] reconciliation_status: reconciliation healthy and fresh
- [PASS] parity_thresholds: parity pass and fresh
- [PASS] portfolio_risk_status: portfolio risk healthy and fresh
- [PASS] alerting_health: alert webhook evidence is present/recent
- [PASS] event_store_integrity_freshness: event store integrity fresh with zero missing correlations
- [FAIL] day2_event_store_gate: day2 gate not yet GO

## Evidence Artifacts
- F:\Environement\git-repo\hummingbot_custo\hbot\config\coordination_policy_v1.json (sha256=2ebb09ec616e921ce0d7f9ae1e978f7216984939c0244488f15b63089caf2815)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\multi_bot_policy_v1.json (sha256=eddded58c3923cbf14686e297084686d49b74ab0766565adbaeaf1270add35dd)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\parity_thresholds.json (sha256=71cb2b0dbf461ba1b88191308b4daaadf2433740aaace9cf8197c9185d7c8224)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\portfolio_limits_v1.json (sha256=e03aacc170d2a0dec6236846a3614d55316f3a1ee107f660e102f76f546dad03)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\reconciliation_thresholds.json (sha256=5ea94828eb8c5736c66a50d5c3331a87d9a4c14363d680813638dfa1be9519cc)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\strategy_catalog\catalog_v1.json (sha256=2fbce9b3ede5a35e442824f982098e834d34950606521959e007e7f038ef5380)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_a\minute.csv (sha256=bd3e782ec0234a416337966ae43daab4536ddf08ac7b03aa8ce3234d2b77dda9)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_d\minute.csv (sha256=a9be7cdb628f2647c364dfcabb9f0fdff4780721d9dbeced6f5a4b4e793d0dbc)
- F:\Environement\git-repo\hummingbot_custo\hbot\docs\validation\backtest_regression_spec.md (sha256=7fa32faa3844b80a566d3243a69b26ada9be74f8d66776a4fbd045e1b881acd9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=5d4dc1852f3bf3ececec21d9cfca4a6d6f42c9fccceaec5e4e0030ed66b0183c)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=bcf931915d23f498cc2052ffe0bb9c2b68c8ff1aa8da941a71131f6092a2c57d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=f543b6df85bb1a3ef15749a60b036bb1ea60144730f99afe5960fdb50c5e4f99)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=414cab6d8d4c2f0dfdbff9be780ee7461678d81588e2bd081162dca54db8b50b)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=bb6bb60f3ef9e9eb3226e1900dd3b00140967c719165d7ed27b591cdb3b23acd)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\coordination_policy_latest.json (sha256=d34d75938b62259afc1fdcf19e722086e7cb1e04010c0f099e08173d0e93d3e9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=aaa3e9e336481e5e6aaf06d2ebb60a5c66e654583fa5cd0838167523ba64308d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=e9e547ec62d0f363b4dca93a530ca073c0f978b9f83f39839868ad6d8135050f)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=d0899f8f3f93362843e873f849c67ea5a20e262d1c0a9d6e48422c72260c1a41)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\latest.json (sha256=e976d3c1fbe6197859fcae63c37f8a4cf5b393872e03faa6b50ddae3e054a510)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=0e6ac6ffd14e5b433b9e31f59fe4ebcdb06abf3df72a2badfcde015ea911f404)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=1f57962f73645334c24ee0a908bce491842b0ad1668d30bf2338487876c9d95b)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=979799b39602e3e9b3ca9a5aeaf1c3e9a165a016bc1b87cd73962f6726d52b94)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=bf815ebbe21daadac89284b1f12b68fd02f67867fecaf34dc24e0cf29f487c50)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_coordination_policy.py (sha256=3c11873a867b47073a4d2cba8b6b41db2b85271389d50418f31be1131aae4f3e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_multi_bot_policy.py (sha256=9c7b50f6ae693884964a9cc6234e38b670561e7a10399c04b459e8d651243ddc)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_strategy_catalog_consistency.py (sha256=b3efe7873369592ff0b5747406683765e547f9ce1bb888e66b226c998f1c0d2e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_backtest_regression.py (sha256=b81418c240c277eebd1a685c103a77936d890ec8d763bc0d7412b0c86ca5ea64)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_cycle.py (sha256=c20f4bceef356a572433a936500007247e8a5d74fab6a18727ada4c28244d1cd)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_secrets_hygiene_check.py (sha256=ee612b9c38833b576330d88597dacc8b6bbeb02e8d357ff97d8e384a207e2e9c)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_tests.py (sha256=5156a5f50997aba7332de8c4349669fee9ad5c59fc5c45395c02790f258a8961)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\utils\refresh_event_store_integrity_local.py (sha256=158cf50897bea64eb3e48b29ec1ecaf205704a1a6ad06d70dde9640de33a4c36)
