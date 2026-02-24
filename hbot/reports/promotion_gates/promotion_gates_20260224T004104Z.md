# Promotion Gates Summary

- ts_utc: 2026-02-24T00:41:04.993506+00:00
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
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\accounting\latest.json (sha256=8e9542b724a81179cc2e853e7f5f3e33786e54ca3d13373f78a4bed65474faf8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\analysis\post_trade_validation.json (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=7b776853e99d7fd80f147d65274b31dd80186d6ab96e234a6981f897d38efb62)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=14777ce77cb71c7d2e01e81b7cc6c941f0fdfb364283b63b541e488e8f75c5d5)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260224.json (sha256=7db1ad5591d7d58f502138133ba0c72240e4e67c2eeb85bc0216667878639233)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=b0f0b2297fe01b896d1b95c2f85456d335b0b1b2e54ef07303b18f1bd42999f4)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\market_data\latest.json (sha256=456bc6b9878c217f8862d3972cc6493c587bfb592d46863972e31d18cd2e1661)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\paper_soak\latest.json (sha256=)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=6fb9130def26f92d350cec524291889329b64c1c6376680dd1bcadbc942d04bd)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\coordination_policy_latest.json (sha256=878d91d15e06552f0d924165ef37fff2acc765920f911457d6b8e3dddd1995bd)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=6a523799aa963f00b9831bbfea348d480068ac5cad1196b62d823a72c9a654ff)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\ml_governance_latest.json (sha256=63796d67661c6b447a51f0372504d5b1e81d6ee2761aa99eb9171b00bbc87e5d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=0bb69bf91c5b67b4434c135025301c2fde2b84d1d51d230ed324ab6203e7e7ff)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=34656b61bbf6f6e588e080d6cdd10d4daf63d106eb434a29bf9a92f17954bc82)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=b2c0e4c9a7e52b6ea37ea5f7301720a9641e432dd6b26a34117293fc3e84fe99)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression_multi_window\latest.json (sha256=f002778697c0566051e0e6cdf491c65ad6433545d135ec09fb29afd7f024bbb8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=9a3285a43574e712484e3defb8158fbf51c8a88c33ad9cffca13cdccfc0bcbc1)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=7e41c75748ca6e1fa2f25c997b6dc44e5128a47429415df7ba16cfd6dbf934cf)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=7aafc8627fca678c9ec949e19edbdd19b486bf339c0e46f2a23a8588a5d366e8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=15baf38549430efbad78da97716bf684b0d1a221f9b9b0fc65b6a7e8427a476b)
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
