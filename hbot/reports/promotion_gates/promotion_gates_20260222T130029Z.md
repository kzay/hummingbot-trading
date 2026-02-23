# Promotion Gates Summary

- ts_utc: 2026-02-22T13:00:29.818413+00:00
- status: FAIL
- critical_failures_count: 2
- evidence_bundle_id: 6caae5274f857741bcb5765d6e8b1998094d53bde693a7b11df167090a3f836f

## Critical Failures
- unit_service_integration_tests
- event_store_integrity_freshness

## Checks
- [PASS] preflight_checks: required files present
- [PASS] multi_bot_policy_scope: multi-bot policy scope is consistent across risk/reconciliation/account-map
- [PASS] strategy_catalog_consistency: strategy catalog configs resolve to shared code and declared bundles
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
- [FAIL] event_store_integrity_freshness: event store integrity missing/stale or missing correlations detected
- [PASS] day2_event_store_gate: day2 gate not yet GO

## Evidence Artifacts
- F:\Environement\git-repo\hummingbot_custo\hbot\config\multi_bot_policy_v1.json (sha256=eddded58c3923cbf14686e297084686d49b74ab0766565adbaeaf1270add35dd)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\parity_thresholds.json (sha256=71cb2b0dbf461ba1b88191308b4daaadf2433740aaace9cf8197c9185d7c8224)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\portfolio_limits_v1.json (sha256=e03aacc170d2a0dec6236846a3614d55316f3a1ee107f660e102f76f546dad03)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\reconciliation_thresholds.json (sha256=5ea94828eb8c5736c66a50d5c3331a87d9a4c14363d680813638dfa1be9519cc)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\strategy_catalog\catalog_v1.json (sha256=2fbce9b3ede5a35e442824f982098e834d34950606521959e007e7f038ef5380)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_a\minute.csv (sha256=bd3e782ec0234a416337966ae43daab4536ddf08ac7b03aa8ce3234d2b77dda9)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_d\minute.csv (sha256=a9be7cdb628f2647c364dfcabb9f0fdff4780721d9dbeced6f5a4b4e793d0dbc)
- F:\Environement\git-repo\hummingbot_custo\hbot\docs\validation\backtest_regression_spec.md (sha256=7fa32faa3844b80a566d3243a69b26ada9be74f8d66776a4fbd045e1b881acd9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=793178f3a932bbe8f97ab187cd852c2d08532035fdc8b0df321b78cf6df17ac0)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=b75aeff13e96348f0cf688ba25d81a8271734831f66412fffa8de7022c0edcb8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=a87bf09cd34cce96db006c97a06545c7a2fbd7fe46d6a2f519c1c06c16121d72)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=b949615ac4640945db8785f008e596246895e4f68b8ce39f593a30b9f139e232)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=43182c11ebc0ef99fc77a3d702b3032bd066bdbec6644d695f8f2f3e0c667bb0)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=06076f664cb95406c2f995cb404412545064fa5e75e5e4f07282d068dfe41ebf)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=6b73695e8849714085160165d2d6bd478858a10b08aecc4bf69f25f34f0742e6)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=ac86485773c983ff0bbd740be61c020fcc54020aeb6b4ac3d6bde4dcd64b1491)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\latest.json (sha256=f676bb5969805fc3b17497aba89969064f0ba7869bcca0bea16b4a4250fc9ff0)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=3761f01f25156d7a22467fee4b9c800d344dc9cb819fa77a1abaa472797a2d91)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=cb99739fb959b4c3d13b3aa30fd58d16ed122d75afcf44a6115ae047b6266f43)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=83163ec0d6abb7b79ee1ec37f4bfec44ae597c5f7a221537e141cff78c13648a)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=96248b9420d1607d0e9e00b0720408e0f9c58749de0c0a3450235c37f32e5d33)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_multi_bot_policy.py (sha256=9c7b50f6ae693884964a9cc6234e38b670561e7a10399c04b459e8d651243ddc)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_strategy_catalog_consistency.py (sha256=b3efe7873369592ff0b5747406683765e547f9ce1bb888e66b226c998f1c0d2e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_backtest_regression.py (sha256=b81418c240c277eebd1a685c103a77936d890ec8d763bc0d7412b0c86ca5ea64)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_cycle.py (sha256=c20f4bceef356a572433a936500007247e8a5d74fab6a18727ada4c28244d1cd)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_secrets_hygiene_check.py (sha256=ee612b9c38833b576330d88597dacc8b6bbeb02e8d357ff97d8e384a207e2e9c)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_tests.py (sha256=04c540683092813180fa070f29ff46b2bf87df62d9481bbc4ff8a5db530eb34e)
