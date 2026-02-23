# Promotion Gates Summary

- ts_utc: 2026-02-22T17:28:11.278078+00:00
- status: PASS
- critical_failures_count: 0
- evidence_bundle_id: c2642649d1c0bad6f6b6aa0e94cadd482eb644db1addc3f2999dbd87d7bb2e93

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
- [PASS] day2_event_store_gate: day2 gate not yet GO

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
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\accounting\latest.json (sha256=fc4cc570d00b1b037265969773040bcda284c772af6729c6e6fee15b2196540b)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=2fb4e35127f50971de8155d8e7279f638781ff7869d5031f76fbf0c10bb97083)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=5788e78159c09a0ae5fe0c56d35e2289e022461512c8744db185e49ad3784311)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=932aa6ba8334094c85b126daa8a13ff72a303d93499532cb772d9ae921770b41)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=3ade235fc687dfc05b815a73bde961f41e7e44b65558faf71122ff53bbac7d26)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\market_data\latest.json (sha256=edfff49cc8ad93c9e1f8f23d5c0dbc34784a0d8209b141a25ea86a94c53da052)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=0950c61a3c3ec7119a275d18525b950a13e78f793266fba186636da9b1a4160c)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\coordination_policy_latest.json (sha256=03ac66740792265b379303e1f4f314296db7191116441fd1e0b91dfefb3541af)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=77314612ccbd5f408a8020126cd9fabbb0c02c37ff5632d77360e2aa11cfa68b)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\ml_governance_latest.json (sha256=98b6d94228e0fb3847df90bd23ea0e6dda31eaeed8e8fd54392da90ebff0ebae)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=b6b81569f7d365862806c2cdb13cc9716f29f889a6d88b49ad896b5f0828b279)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=f9e88c425998d290e271f6056afd683103f36b7b9cfbca49cbcc0e8cca604e2a)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression_multi_window\latest.json (sha256=e81fadf1be9ac3c805b7ab9499ee97bc0ca9765fed85d9179c1bbb12e2bcd799)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=7a7a9681efc98070c498e25f969d56b186d393e69953ccfd16c660d0ca82bd49)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=4eff936f8138f7d996455e47d58ad17061e15d654fd5328b74a6894157b99964)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=db17b01a7366783d29d4d2fbd14df4fe7faa379466b0978ec798e34b52d2d794)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=407c593fac85ed4f35ab2702254ea9ffbe4d06b8969284e1a6a75bbadb12d128)
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
