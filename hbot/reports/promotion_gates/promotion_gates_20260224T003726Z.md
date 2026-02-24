# Promotion Gates Summary

- ts_utc: 2026-02-24T00:37:26.090404+00:00
- status: FAIL
- critical_failures_count: 1
- evidence_bundle_id: a27af2619cc5433818b0cc62b6a4a743a33ffaef7dcc1809952e4c9f5779d27e

## Critical Failures
- alerting_health

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
- [FAIL] alerting_health: alert webhook evidence missing or stale
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
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\accounting\latest.json (sha256=9633592fbba7d75c076695360777e10f9eda8e3d5fad65d79c52b6670e0eaaa4)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\analysis\post_trade_validation.json (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=808f6ab0e89af19457dcd24760ef64e1530eed5a143c4aedc5c98bb338886787)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=eaefe0485420fa528fa55adf0274b57161a7fc356d5fd86f001400ba596d219d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260224.json (sha256=26e0390ec8a5c63514a79ff898800d714ba4e87672f5e305021c59f8447c9ec6)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=9ee197511b3ef5be5f7743ebee347d7a9b76890b71da06d32dc0a1259ff29bb3)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\market_data\latest.json (sha256=3225b2675abef220543430e59318bfb5a2ec45e53a5c0c4d3cdd60f2310c5dea)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\paper_soak\latest.json (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=ede5ec337bacb624d2fd4f35f631c2faad4f15a3f44720c6b53e923d6c8625c6)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\coordination_policy_latest.json (sha256=326a8de81efd07a6e6b347ebe5ecf985b47b6c4a4debe95bd9391d537a043a6a)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=d0837dcada9dd6100cd747270970c5041eb197d7bc14148b1b71c8fcb0ea3ad9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\ml_governance_latest.json (sha256=12698eb1837deac1c270f48e2c616a7f8b0353827dc10d07834ea54f0baa1f66)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=e60643b131f367365140cdc78e65dcd113d3d041bb3f738d0da54ca64036f577)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=cf5e1f6968452d6980bade333d809da8a3e2d977806a12535180e7cb0b998439)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression_multi_window\latest.json (sha256=fb300e1b92f181066dd9d9d3500da35a93cc0a78ec6ecb0438b82e280262d533)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=104d91d7fdcb27d7320add816ea1a10a7ca1df55507fdf718a544178646ab2cc)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=28c2374bbabb76dc44fc2d1af8b3566a581a85e181499c7690c87467a80c3f0d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=be90a08bd43b1a2d08db1de0ee81490e64bf141036a66d62f9c91db45a4cb44b)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=aeea3d4f8966284832c371831d64663d8cecf4478852a1e582ab3bec5dadb98f)
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
