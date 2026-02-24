# Promotion Gates Summary

- ts_utc: 2026-02-24T02:34:53.711263+00:00
- status: FAIL
- critical_failures_count: 3
- evidence_bundle_id: 1e6134477e92674185bdf1e9ad062f92c5a00039f85ee71c90de0ed55f76ebdf

## Critical Failures
- replay_regression_first_class
- parity_thresholds
- event_store_integrity_freshness

## Checks
- [PASS] preflight_checks: required files present
- [PASS] multi_bot_policy_scope: multi-bot policy scope is consistent across risk/reconciliation/account-map
- [PASS] strategy_catalog_consistency: strategy catalog configs resolve to shared code and declared bundles
- [PASS] coordination_policy_scope: coordination service runs only in policy-permitted scope/mode
- [PASS] unit_service_integration_tests: deterministic test suite + coverage threshold passed
- [PASS] secrets_hygiene: no secret leakage markers in docs/reports/log artifacts
- [PASS] smoke_checks: bot4 smoke activity artifacts found
- [PASS] paper_smoke_matrix: bot3 paper-mode intent verified
- [FAIL] replay_regression_first_class: replay regression multi-window failed (rc=2)
- [PASS] ml_signal_governance: ML governance policy checks passed
- [PASS] regression_backtest_harness: regression harness PASS
- [PASS] reconciliation_status: reconciliation healthy and fresh
- [FAIL] parity_thresholds: parity fail or stale
- [PASS] portfolio_risk_status: portfolio risk healthy and fresh
- [PASS] accounting_integrity_v2: accounting integrity checks passed with fresh snapshots
- [PASS] alerting_health: alert webhook evidence is present/recent
- [FAIL] event_store_integrity_freshness: event store integrity missing/stale or missing correlations detected
- [PASS] market_data_freshness: market data artifacts are fresh with hb.market_data.v1 rows
- [PASS] day2_event_store_gate: day2 gate not yet GO
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
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\accounting\latest.json (sha256=777c5799452942ac4df3a78f98aeabd207de7f28c42a91d4f440c45679fe9aeb)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\analysis\post_trade_validation.json (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=08f27abe04db4d83c9e2940c0f0ccd147936fe3dc35b67cac3dd8a35a312d51f)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=4ec2181084a5b9a45146733e213af2c7f88d3c5f40863230e26cf734adab599c)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260224.json (sha256=28c3167c4d2318d96b11e7676c30f30a8dd1558d75ef5a1a414375316eaa9b06)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=05a7752aa4b957a819a3837d6b448b90865dbc3d8253b8cb21fefe15852ad40f)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\market_data\latest.json (sha256=6cc6f6df284d455045a9d074d4af00603213629bf143477ee2c76ed28cecd023)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\paper_soak\latest.json (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=b1f6af5fdb1aa2173a6a99a94a897e10826a482c0bffd56f9b1128b9f5e44524)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\coordination_policy_latest.json (sha256=4e6c19a5bb10118b5f1c6c3a7c943fe9943669060d2ea83edac9bc9c54020b00)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=446ffd1f35c33738516d9cffdd7b62af2d3b1231ce97a0a312b9572ddcfba965)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\ml_governance_latest.json (sha256=b4c0b2abe2ecae41dda1be661d8425d5d265f117296a7f19f23cc2dbef708682)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=2a94ba53bc62697e1ffde1550f2635a5e2253b741aaaad541d3cf6c524ec0bdc)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=b6243125069b78c7155b6a052e15d1003673f8f8cf5fd67d23ccfcb814e60c20)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=72d63d5e83043cb96b30ed68b4727127cd8941fe3770d9ab5274fb2f87e8a28f)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression_multi_window\latest.json (sha256=65fd30fce43ba104470ab4e2dfe4c9a04e68b4d7df7a0936c8ec329d7480c3ed)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=fe428af412b3ec3ed8ce75674416dad38bd77dc1f7da691e1e1e8f2e801227b8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=2abef3936512d68d3c9e4c61f149ff0193ae5c4468c098d9bcdb1487cf84ecc6)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=2a2d4012bafe852e500304cf46d57301eed22f2e1d3dd7da24cb759c3c9c30b0)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=35ef622003bd601c0ae053c7171d3122c35644e74789bc2a3f20dc784ff4f683)
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
