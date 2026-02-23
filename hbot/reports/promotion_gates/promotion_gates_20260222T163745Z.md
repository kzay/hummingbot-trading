# Promotion Gates Summary

- ts_utc: 2026-02-22T16:37:45.728118+00:00
- status: FAIL
- critical_failures_count: 1
- evidence_bundle_id: ab36adab3d068a4639375db331378734db40ae4507691956138bccb780176147

## Critical Failures
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
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\accounting\latest.json (sha256=b48b1014ae751d637d921ebb177f7ef28b415b1e8e71e5793f269a21ee130b5d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=4589d75334e3aa4af2d0df1ffebeb8710045759cf9314b214e5836d2e82412a4)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=f26e63729b42d4e78877331b0db3442f667d85182408f7c465a3874bd5c69849)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=29fefd8698f30ba177aaea51b25255476f75be597cb822fb8b752316c9a163c5)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=cb82942abe4a0d1429af382e1cfb3f09c658ac7610a1fdcb4c19bfa71800989f)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\market_data\latest.json (sha256=eaa66bc6c54170c128e0a63d05d924e7b256289909f6abc9671a80a440940f0e)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=43cc2d0eb78a32ccbb841897565f6a68183fda4838be6ddf264f37fdaf65b9e2)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\coordination_policy_latest.json (sha256=3d3a17d39a5e985c1baec51abddefbbdb78b36bed22079122b8a185ca5d8e06a)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=24d89c8b769e7c53c538e33a4b060bdcfe9faa8dc7707afa97d6356d4bef4639)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\ml_governance_latest.json (sha256=2d16bc096def0b3b2606751d781adeb43413aac67c42041b759f1a36cf224b2a)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=2efabbd1dc637007007a38f300cb5121be4c4313129094d70125319c8489e850)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=277961ed2e99dbf0a7772fd27edc686f5f81a5bb46b16b4768471fedee27aa9b)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression_multi_window\latest.json (sha256=e81fadf1be9ac3c805b7ab9499ee97bc0ca9765fed85d9179c1bbb12e2bcd799)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=3fbf7be9db8ff3bb69920361f448dcb40f19e3639e97c91d215f2d75143c234e)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=6e023c3812f208a6e75d01f3236257951a7799d330a4cc1ef64b5d3035c3478f)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=e70ba2c551107bdf93e175df952f4193937fd73c61c4afb81e748ac880f67eae)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=a55430d70bc2064cb6ed41ea7a6f209f6e0e23dde137f2d5515aa85ae65da9a5)
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
