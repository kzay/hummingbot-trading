# Promotion Gates Summary

- ts_utc: 2026-02-22T12:59:36.929107+00:00
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
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=8e9f442c3af494f56851d2e8528fbf5aa1fa582d543a6cc982ad009b116a9172)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=b75aeff13e96348f0cf688ba25d81a8271734831f66412fffa8de7022c0edcb8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=a87bf09cd34cce96db006c97a06545c7a2fbd7fe46d6a2f519c1c06c16121d72)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=b949615ac4640945db8785f008e596246895e4f68b8ce39f593a30b9f139e232)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=1caabf2ec0830b491dc2c7ac964e963ed0922d469ecc61661924bd2fa24e2896)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=44f919fb875568e3d9e4487c0d1e44b6cae35d3a2eab2b8295ef9635ce47eff3)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=daffa4756868c1831e31ad08e292d8dffbb04c9488e167886c9081af4178f3a6)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=c5a8e0cd6cbec4b0ef7515c05eb70dc533eb59e142ea1f6b1322982c3db0676c)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\latest.json (sha256=f3d007b49fd305dc7e41d1a5849a8ea84cf9a4c7feaac549eaa44a32970270f1)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=1cb56b9cff9a116a9f5e86dcf51a7db72831ef4410cdc2f47001b576accb5455)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=b1103b3cfc003c5de90c13575005c137198d8a1e703e2aaafe8314ca117873ca)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=d631f60696bee90a8cc0879bebe633fccbca21d873c737fc7225d34ebad21069)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=144cfbc3d4814e477d3c231d7077ea8b2c16a7e3001ecc2920d7015708dbee3c)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_multi_bot_policy.py (sha256=9c7b50f6ae693884964a9cc6234e38b670561e7a10399c04b459e8d651243ddc)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_strategy_catalog_consistency.py (sha256=b3efe7873369592ff0b5747406683765e547f9ce1bb888e66b226c998f1c0d2e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_backtest_regression.py (sha256=b81418c240c277eebd1a685c103a77936d890ec8d763bc0d7412b0c86ca5ea64)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_cycle.py (sha256=c20f4bceef356a572433a936500007247e8a5d74fab6a18727ada4c28244d1cd)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_secrets_hygiene_check.py (sha256=ee612b9c38833b576330d88597dacc8b6bbeb02e8d357ff97d8e384a207e2e9c)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_tests.py (sha256=04c540683092813180fa070f29ff46b2bf87df62d9481bbc4ff8a5db530eb34e)
