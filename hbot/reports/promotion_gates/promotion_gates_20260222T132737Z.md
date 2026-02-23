# Promotion Gates Summary

- ts_utc: 2026-02-22T13:27:37.875554+00:00
- status: PASS
- critical_failures_count: 0
- evidence_bundle_id: 877906e7900e6e7d6162db98cd3ee157bac86dda62e852868accfc46ede2232f

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
- [PASS] replay_regression_cycle: replay regression cycle PASS
- [PASS] regression_backtest_harness: regression harness PASS
- [PASS] reconciliation_status: reconciliation healthy and fresh
- [PASS] parity_thresholds: parity pass and fresh
- [PASS] portfolio_risk_status: portfolio risk healthy and fresh
- [PASS] alerting_health: alert webhook evidence is present/recent
- [PASS] event_store_integrity_freshness: event store integrity fresh with zero missing correlations
- [PASS] day2_event_store_gate: day2 gate not yet GO

## Evidence Artifacts
- F:\Environement\git-repo\hummingbot_custo\hbot\config\coordination_policy_v1.json (sha256=2ebb09ec616e921ce0d7f9ae1e978f7216984939c0244488f15b63089caf2815)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\multi_bot_policy_v1.json (sha256=eddded58c3923cbf14686e297084686d49b74ab0766565adbaeaf1270add35dd)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\parity_thresholds.json (sha256=71cb2b0dbf461ba1b88191308b4daaadf2433740aaace9cf8197c9185d7c8224)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\portfolio_limits_v1.json (sha256=e03aacc170d2a0dec6236846a3614d55316f3a1ee107f660e102f76f546dad03)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\reconciliation_thresholds.json (sha256=5ea94828eb8c5736c66a50d5c3331a87d9a4c14363d680813638dfa1be9519cc)
- F:\Environement\git-repo\hummingbot_custo\hbot\config\strategy_catalog\catalog_v1.json (sha256=073f834b75a6cf53e51770fb942e8a561a2abf42725711d1f4bf10c16ce55f0d)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_a\minute.csv (sha256=bd3e782ec0234a416337966ae43daab4536ddf08ac7b03aa8ce3234d2b77dda9)
- F:\Environement\git-repo\hummingbot_custo\hbot\data\bot4\logs\epp_v24\bot4_d\minute.csv (sha256=a9be7cdb628f2647c364dfcabb9f0fdff4780721d9dbeced6f5a4b4e793d0dbc)
- F:\Environement\git-repo\hummingbot_custo\hbot\docs\validation\backtest_regression_spec.md (sha256=7fa32faa3844b80a566d3243a69b26ada9be74f8d66776a4fbd045e1b881acd9)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\backtest_regression\latest.json (sha256=d463ff427be6b2ad8bb3e2f3da6355659611eda25fdc5eb0b6fc0787d58392a0)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\day2_gate_eval_latest.json (sha256=42c406aebd529a16dba70d1df4c1e48a0c71da29847219d222b1687a057f0b22)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\event_store\integrity_20260222.json (sha256=4d75d4a0d4cb40fdd5116d691191b10b15854bd3a7d57f6f987a418bb712a4d8)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\exchange_snapshots\latest.json (sha256=0f97f4cb6ece0cdc69fe8dc4175223c993b5538d19bd72777ba99e6aed0d1f29)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\parity\latest.json (sha256=e92ae81f77e29278b69aff7d5550dc0915809e2183fccba66af0940eeefe22e0)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\coordination_policy_latest.json (sha256=efe6ddbf463469d1b0dab271fcf00f1b0f00da8c990d2dd50131050089f48138)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\policy\latest.json (sha256=d0ef57392b6d579f12e019bfb5e7a232a02b610979d89aa2db035b3808cbea38)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\portfolio_risk\latest.json (sha256=8b22387be86faa60306a025520e1aedb22110509e6190914c9432eed292f9ca2)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\last_webhook_sent.json (sha256=6071d8307c61a3e11d8838f6e633a0ca55a7aa2d6771205108da93487ca7c88d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\reconciliation\latest.json (sha256=b8c4f8abbb07bad6788ef206ac801bc6e3163283fbc19e22d4a37bd81205d35d)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\replay_regression\latest.json (sha256=d961077a10581572db62682df705a9d86144c5ecba183fb422cd962308f2e7d0)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\security\latest.json (sha256=4951f5dc5746a36f5d5ddcf5ffa0781fa310b5e6cd7951b2776752cb20a341c3)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\strategy_catalog\latest.json (sha256=4da888851451a8d79eb6a05569dfe05c00884fa614e19a6c2afb7f7806f07897)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.json (sha256=2fbca8692aaffd9f83bca21f2243dd416900cdda94311547d8e1d2bd49040091)
- F:\Environement\git-repo\hummingbot_custo\hbot\reports\tests\latest.md (sha256=fd250baec991b9135ecf961b90b0b7be20dea009623d3790cb744c3cfcb459e8)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_coordination_policy.py (sha256=3c11873a867b47073a4d2cba8b6b41db2b85271389d50418f31be1131aae4f3e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_multi_bot_policy.py (sha256=9c7b50f6ae693884964a9cc6234e38b670561e7a10399c04b459e8d651243ddc)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\check_strategy_catalog_consistency.py (sha256=b3efe7873369592ff0b5747406683765e547f9ce1bb888e66b226c998f1c0d2e)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_backtest_regression.py (sha256=b81418c240c277eebd1a685c103a77936d890ec8d763bc0d7412b0c86ca5ea64)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_replay_regression_cycle.py (sha256=c20f4bceef356a572433a936500007247e8a5d74fab6a18727ada4c28244d1cd)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_secrets_hygiene_check.py (sha256=ee612b9c38833b576330d88597dacc8b6bbeb02e8d357ff97d8e384a207e2e9c)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\release\run_tests.py (sha256=64a712ef8858dffdbf479a09414728cb750317087172e3d128a12b131897b3e6)
- F:\Environement\git-repo\hummingbot_custo\hbot\scripts\utils\refresh_event_store_integrity_local.py (sha256=158cf50897bea64eb3e48b29ec1ecaf205704a1a6ad06d70dde9640de33a4c36)
