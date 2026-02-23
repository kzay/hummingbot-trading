# Promotion Gates Summary

- ts_utc: 2026-02-22T16:18:22.975545+00:00
- status: FAIL
- critical_failures_count: 2
- evidence_bundle_id: 95ee7e5003b0cab0898ef4dd49ec0b3cabc2f2c6e5437229f45f794f1d58908f

## Critical Failures
- secrets_hygiene
- day2_event_store_gate

## Checks
- [PASS] preflight_checks: required files present
- [PASS] multi_bot_policy_scope: multi-bot policy scope is consistent across risk/reconciliation/account-map
- [PASS] strategy_catalog_consistency: strategy catalog configs resolve to shared code and declared bundles
- [PASS] coordination_policy_scope: coordination service runs only in policy-permitted scope/mode
- [PASS] unit_service_integration_tests: deterministic test suite + coverage threshold passed
- [FAIL] secrets_hygiene: secrets hygiene check failed (rc=2)
- [PASS] smoke_checks: bot4 smoke activity artifacts found
- [PASS] paper_smoke_matrix: bot3 paper-mode intent verified
- [PASS] replay_regression_first_class: replay regression multi-window PASS
- [PASS] ml_signal_governance: ML governance policy checks passed
- [PASS] regression_backtest_harness: regression harness PASS
- [PASS] reconciliation_status: reconciliation healthy and fresh
- [PASS] parity_thresholds: parity pass and fresh
- [PASS] portfolio_risk_status: portfolio risk healthy and fresh
- [PASS] accounting_integrity_v2: accounting integrity checks passed with fresh snapshots
- [PASS] alerting_health: alert webhook evidence is present/recent
- [PASS] event_store_integrity_freshness: event store integrity fresh with zero missing correlations
- [FAIL] market_data_freshness: market data freshness check failed (rc=2)
- [FAIL] day2_event_store_gate: day2 gate not yet GO

## Evidence Artifacts
- F:\Environement\git-repo\hummingbot_custo\hbot\config\coordination_policy_v1.json (sha256=2ebb09ec616e921ce0d7f9ae1e978f7216984939c0244488f15b63089caf2815)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\ml_governance_policy_v1.json (sha256=842b3cc4f118caaf3632df2eaffaa59325f875fda7054fa00efd7c084fd5eb82)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\multi_bot_policy_v1.json (sha256=eddded58c3923cbf14686e297084686d49b74ab0766565adbaeaf1270add35dd)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\parity_thresholds.json (sha256=71cb2b0dbf461ba1b88191308b4daaadf2433740aaace9cf8197c9185d7c8224)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\portfolio_limits_v1.json (sha256=e03aacc170d2a0dec6236846a3614d55316f3a1ee107f660e102f76f546dad03)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\reconciliation_thresholds.json (sha256=5ea94828eb8c5736c66a50d5c3331a87d9a4c14363d680813638dfa1be9519cc)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\strategy_catalog\catalog_v1.json (sha256=073f834b75a6cf53e51770fb942e8a561a2abf42725711d1f4bf10c16ce55f0d)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_a\minute.csv (sha256=bd3e782ec0234a416337966ae43daab4536ddf08ac7b03aa8ce3234d2b77dda9)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_d\minute.csv (sha256=a9be7cdb628f2647c364dfcabb9f0fdff4780721d9dbeced6f5a4b4e793d0dbc)
- F:\Environement\git-repo\hummingbot_custo\hbot\docs\validation\backtest_regression_spec.md (sha256=7fa32faa3844b80a566d3243a69b26ada9be74f8d66776a4fbd045e1b881acd9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\accounting\latest.json (sha256=8cc21b43d0fd0185041e9962e6df9344237bcc4da21851d0e91361577c50485d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=439e842734675d3c5bf11ead7d7ef3cdaa6699d10bda93e1a7f7a50ada8b0c31)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=aceca906f24d8963fc5b822a7265f4df3e976f6ddfc733fa74c0b1ad5fcb3a37)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=14854dc7a5a5e4a5ebd9b543f9e6c8de0d07e3ffdfb37cd4acc82c12300c9983)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=d719352bf1bf7cf88816306543140e7f52c51f3e98c2fd1ca4514edb7f9ce025)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\market_data\latest.json (sha256=1fcaee883c3f07c130bed686ea87c4d69ee38321d2afefc1a0b65bd30b8bd156)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=346e782874c53ce291d6cd8ff0667c56fda86af56747d8784bc8d72900f59d68)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\coordination_policy_latest.json (sha256=5196fbd909e51b3ffeb96bfe7c3e94a68f5c66b6ffcf2671f2363fc366ccbbee)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=d92e1200eb6e05e39eb775e6f8ffb750994a00b335c1b3fdc6d4546992e85ca5)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\ml_governance_latest.json (sha256=1c5809c0d3a46f765ec85cb7cdffc0b7344f7c0facc4406cbeb078394fdf7ac2)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=6855ed88ebf5f2c01627aeb7a3395fcd282e6479b1dc86ce4fb850de4e698a08)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=a0478d284263487d07aa2f801c019eb8ddf2cca61662bbb1c2a0267feb1d605b)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression_multi_window\latest.json (sha256=205335ad95810b3959d8117569b1cdef1d195ef25e15a31a60877d16a6267b30)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=f19470c5f8f2ef4aa3f3641d92a0ed837bbf6cefed1176da12ec7300d4e4e535)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=9b75f5f6b58e2f157b6ed587f2eb4657efa7002ea4f1f22a8e43cac823791f9e)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=1bcb3c029240cd906401f966a6be59fc77976098e2bde9c7db2a9a632f463ef8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=35a12372a96fc9f338d31b1c86ec9cddd550687e000df5b636e04e823e32de3e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_accounting_integrity_v2.py (sha256=f8ea3ca3b49fac7ed751c2a716cb98782a4bea61c0f3faa2bc0358a64c379c1a)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_coordination_policy.py (sha256=3c11873a867b47073a4d2cba8b6b41db2b85271389d50418f31be1131aae4f3e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_market_data_freshness.py (sha256=5720184733fa2121cf001d64ca20e932aece2217972b8abb081a7d569788b8c3)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_ml_signal_governance.py (sha256=62a86450fdaceb906b86453145b5e406a5e5998660b92c3abe1192d104367dd2)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_multi_bot_policy.py (sha256=9c7b50f6ae693884964a9cc6234e38b670561e7a10399c04b459e8d651243ddc)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_strategy_catalog_consistency.py (sha256=b3efe7873369592ff0b5747406683765e547f9ce1bb888e66b226c998f1c0d2e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_backtest_regression.py (sha256=b81418c240c277eebd1a685c103a77936d890ec8d763bc0d7412b0c86ca5ea64)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_cycle.py (sha256=c20f4bceef356a572433a936500007247e8a5d74fab6a18727ada4c28244d1cd)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_multi_window.py (sha256=f434f747df2fe690307138cc94a48b259ee1eac5c0159572e0e148f4e4db091d)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_secrets_hygiene_check.py (sha256=ee612b9c38833b576330d88597dacc8b6bbeb02e8d357ff97d8e384a207e2e9c)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_tests.py (sha256=64a712ef8858dffdbf479a09414728cb750317087172e3d128a12b131897b3e6)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\utils\refresh_event_store_integrity_local.py (sha256=158cf50897bea64eb3e48b29ec1ecaf205704a1a6ad06d70dde9640de33a4c36)
