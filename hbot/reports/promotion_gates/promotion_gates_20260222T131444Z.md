# Promotion Gates Summary

- ts_utc: 2026-02-22T13:14:44.269194+00:00
- status: FAIL
- critical_failures_count: 2
- evidence_bundle_id: 60fc3417f7fd3ee4bb8e5cec16aca9dded89a8e6c51f92b0880a43f880635d74

## Critical Failures
- event_store_integrity_freshness
- day2_event_store_gate

## Checks
- [PASS] preflight_checks: required files present
- [PASS] multi_bot_policy_scope: multi-bot policy scope is consistent across risk/reconciliation/account-map
- [PASS] strategy_catalog_consistency: strategy catalog configs resolve to shared code and declared bundles
- [PASS] coordination_policy_scope: coordination service runs only in policy-permitted scope/mode
- [PASS] unit_service_integration_tests: deterministic test suite + coverage threshold passed
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
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=265a2bb9c475f7a6374ce70b71004a4a9b951514ef7b6599a8512a53b38a51fd)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=52c3e60b9a32d49b1b626f537a7c45912b8cc85568bc35df16bece8f9dbebf87)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=a87bf09cd34cce96db006c97a06545c7a2fbd7fe46d6a2f519c1c06c16121d72)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=b949615ac4640945db8785f008e596246895e4f68b8ce39f593a30b9f139e232)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=aa93c8b5f32be1018c67f578f701682b63ac06d381fdb4900b196935e5a9f3c6)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\coordination_policy_latest.json (sha256=c64256943741a3869623db5d03b069868e64f649fde5b0370dc3b70692058c4f)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=b335e4a1ef236f0ea9dbec2ad9346670f8e348d001ca28d6276736898b90821c)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=f234481b02f3968ecc33bd8b3dbb137c87c47e1e39d3a9ae66a8338c3e02f5c3)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=ef4886c9ee4f66d84c86245dbeb4568bad2882a0b6f86078377aff7fc7235c87)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\latest.json (sha256=18d72ca6722b657d38c11d162c9cfcf5d0d2d7a71ae8452c336f20699c7ad596)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=991eba08de0964c43482fd4f884beb2b8462e41f0900601278de6150e1b8ef83)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=68723e6ae2d2ebeb91325ef962d2beb119875136a5892a59cb5c87ccaf41a6df)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=4f2e034b32f1b911858933b788b4c989f8500cef0dcdf260564482c83a984f28)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=f15159aa3043182210831ab2fdf84cf3a45937e7839e1f02d50f71ef533fe377)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_coordination_policy.py (sha256=3c11873a867b47073a4d2cba8b6b41db2b85271389d50418f31be1131aae4f3e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_multi_bot_policy.py (sha256=9c7b50f6ae693884964a9cc6234e38b670561e7a10399c04b459e8d651243ddc)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_strategy_catalog_consistency.py (sha256=b3efe7873369592ff0b5747406683765e547f9ce1bb888e66b226c998f1c0d2e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_backtest_regression.py (sha256=b81418c240c277eebd1a685c103a77936d890ec8d763bc0d7412b0c86ca5ea64)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_cycle.py (sha256=c20f4bceef356a572433a936500007247e8a5d74fab6a18727ada4c28244d1cd)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_secrets_hygiene_check.py (sha256=ee612b9c38833b576330d88597dacc8b6bbeb02e8d357ff97d8e384a207e2e9c)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_tests.py (sha256=5156a5f50997aba7332de8c4349669fee9ad5c59fc5c45395c02790f258a8961)
