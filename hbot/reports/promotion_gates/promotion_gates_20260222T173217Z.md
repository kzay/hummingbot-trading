# Promotion Gates Summary

- ts_utc: 2026-02-22T17:32:17.115783+00:00
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
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\accounting\latest.json (sha256=8ea5c20617a9d0386855492528cfbafe46bd6d3674b41af801a268e25292956c)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=d5a3fdfa176acfdbbb7259dba3707d34b59be1772acf8aea4e2fb48d73c5cb26)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=5788e78159c09a0ae5fe0c56d35e2289e022461512c8744db185e49ad3784311)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=8e3ae81d1c5509bb56263e78fd88b293736741eb52f60e5dda7635ee76bc5ba8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=d3997fe2617d28abca31e748187bc9fa7f16c6cc7a7430f7cca658b4d69408a9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\market_data\latest.json (sha256=73659760def63e257f863b042ae0c67d810396db0d9d14b067d4b6db63731165)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=67b6764189e94cdee9f6c8ae26481fd676747267a3796ccfe03fa63a2c43b814)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\coordination_policy_latest.json (sha256=4a5f221684c5755ab4377bf360cc201cffe3e14cb0608f5affd058fa43a481c8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=4135b8cdd866737f26364f7db28fbc9a345bfbf0e9e42724fd5b14cc65eaa821)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\ml_governance_latest.json (sha256=620b5cd882737089e16b89a210cbb9c5fa06b6b6c6ad762b5dc91f8203407d2d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=33b8fd6b1265f85358a1102850ecec37459f553421043bff635843347c52c87e)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=e664e457f86f4380dd1b9b17c77807ff51afdb492ab30d52708376762ba10e0a)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression_multi_window\latest.json (sha256=06ff7cb399e0db80e4d19f968e8bb70cfbcc2e2e695a5fca66a2cd306ffb41bc)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=265b520267161797ca21e6f499a4a8cdcda19dc7db83eeb982fc40173996124a)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=1781e92092e46b917b5042db17971e7f089970b5e948f8cdc3305ee3eb17ccad)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=af0e61b9d8c9d0c1175d02f5a9e387795befbb0eccb2f22f347e3ca2975390b8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=b939c4e5a20af8e1046c027225e5ab8a097b34f73af6c8d587a6b0613944cded)
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
