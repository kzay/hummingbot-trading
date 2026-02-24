# Promotion Gates Summary

- ts_utc: 2026-02-24T01:28:51.166293+00:00
- status: PASS
- critical_failures_count: 0
- evidence_bundle_id: 5e94d11ce314a9a82d62579c05f39adf5b6c96c83f68ea36262d19db771cbdd9

## Critical Failures
- none

## Checks
- [PASS] preflight_checks: required files present
- [PASS] multi_bot_policy_scope: multi-bot policy scope is consistent across risk/reconciliation/account-map
- [PASS] strategy_catalog_consistency: strategy catalog configs resolve to shared code and declared bundles
- [PASS] coordination_policy_scope: coordination service runs only in policy-permitted scope/mode
- [PASS] unit_service_integration_tests: deterministic test suite + coverage threshold passed
- [PASS] secrets_hygiene: no secret leakage markers in docs/reports/log artifacts
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
- [PASS] day2_event_store_gate: day2 gate GO
- [FAIL] validation_ladder_paper_soak: paper soak not PASS or missing — Level 3 validation incomplete
- [PASS] validation_ladder_post_trade: post-trade validation not yet run

## Evidence Artifacts
- F:\Environement\git-repo\hummingbot_custo\hbot\config\coordination_policy_v1.json (sha256=2ebb09ec616e921ce0d7f9ae1e978f7216984939c0244488f15b63089caf2815)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\ml_governance_policy_v1.json (sha256=842b3cc4f118caaf3632df2eaffaa59325f875fda7054fa00efd7c084fd5eb82)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\multi_bot_policy_v1.json (sha256=eddded58c3923cbf14686e297084686d49b74ab0766565adbaeaf1270add35dd)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\parity_thresholds.json (sha256=71cb2b0dbf461ba1b88191308b4daaadf2433740aaace9cf8197c9185d7c8224)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\portfolio_limits_v1.json (sha256=1fe52b9323c1b0d951f2fe2a1e6a0d2adca2a3e1671b351b0aededb128ee04a0)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\reconciliation_thresholds.json (sha256=5ea94828eb8c5736c66a50d5c3331a87d9a4c14363d680813638dfa1be9519cc)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\strategy_catalog\catalog_v1.json (sha256=073f834b75a6cf53e51770fb942e8a561a2abf42725711d1f4bf10c16ce55f0d)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_a\minute.csv (sha256=bd3e782ec0234a416337966ae43daab4536ddf08ac7b03aa8ce3234d2b77dda9)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_d\minute.csv (sha256=a9be7cdb628f2647c364dfcabb9f0fdff4780721d9dbeced6f5a4b4e793d0dbc)
- F:\Environement\git-repo\hummingbot_custo\hbot\docs\validation\backtest_regression_spec.md (sha256=7fa32faa3844b80a566d3243a69b26ada9be74f8d66776a4fbd045e1b881acd9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\accounting\latest.json (sha256=cec5973ebd169fa75aa8871cafcad4f02d3afbd9a9fb80deab2b6e578d1122f8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\analysis\post_trade_validation.json (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=c59254f067c3d66138afab664ed6b639e1e1c9483c3e9bf97fff7b39fbeaff9d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=993027063139a1fd2e0add8ed7bf987621e06d263762a18601a5f97b735a5b37)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260224.json (sha256=28c3167c4d2318d96b11e7676c30f30a8dd1558d75ef5a1a414375316eaa9b06)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=95251680c74cba581a1ea0c4a1d236770ee43da53519325126646673647f93c4)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\market_data\latest.json (sha256=3792bbbaf4e26e580533b2b3cdf7bfc89f6734be3caeea524e766f8633d6ea07)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\paper_soak\latest.json (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=919b08deaadb846804724b6f17960d1a76aa13c84ac8f14f33acbafecf633969)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\coordination_policy_latest.json (sha256=80de0920cec1e0c5ff604a953a5aff4b537948a53e72f8fa28d976e19c33b397)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=70aa8e83ff917aa20ee53b4341b92fdea795dfe231f9f6adcc70b21a19bdac2a)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\ml_governance_latest.json (sha256=7d5ce3705615bb5932048afe7bf2cfc19fdc8b7da7f86a28b1711da6e1663c3b)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=1fd0c471b59a169aa87d77ba86498eef5b1c4faa0fc46fc794142977648f185c)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=adabb170f15e044420cb67bc03f20bbc6989551cac718bec3ce2f206e85af057)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=43f1adb381d6494fafa3b4f8b0a895f85afc3d65b56fa2366d9e9fa9cc7e8b1d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression_multi_window\latest.json (sha256=ebb70e8cadf2680287a8e4933798ea25e44ba431ad4e558e6c6572f767750cb1)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=230ac113c908dafc2797a8a3b0fb6cea67a4b39f32bba7605a3541c408a444ce)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=d7c8048d005cf08b7376b7a5516c3832b9d305d3e9866e57b128d848c47c9c4e)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=ee2df16e33fe078a7fe53fbf55bc1b44b993dfc8f3ed7e0014f4330bc3d12573)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=6fafe6544c299d3f3381f807ff68e6390ee2d074caec1eb529d2c3ecc4dccfa7)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_accounting_integrity_v2.py (sha256=f8ea3ca3b49fac7ed751c2a716cb98782a4bea61c0f3faa2bc0358a64c379c1a)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_alerting_health.py (sha256=0d08ef9e82b5d8c2cb940f72a877a41a04a12ae31a1eb56882fc41c71aefe6bf)
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
