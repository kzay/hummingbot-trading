# Strategy Catalog v1 (Day 29)

## Purpose
Make controller/script rollout config-driven so adding a strategy variant does not require compose edits or code copying into bot folders.

## Scope
- Shared controller code remains in `controllers/`.
- Bot runtime selection happens via config files under `data/<bot>/conf/controllers` and `data/<bot>/conf/scripts`.
- Catalog metadata and templates live in `config/strategy_catalog/`.

## Naming Convention
Use lowercase snake-style tokens joined by `_`.

- Controller config (no prefix — strategy name leads):
  - `<strategy>_<version>_<bot>_<venue>_<mode>.yml`
- Script config (`v2_` prefix — entry-point version leads):
  - `v2_<strategy>_<version>_<bot>_<venue>_<mode>.yml`

Examples:
- `epp_v2_4_bot1_bitget_live_microcap.yml` (controller)
- `v2_epp_v2_4_bot1_bitget_live_microcap.yml` (script)
- `epp_v2_4_bot3_bitget_paper_smoke.yml` (controller)

## Mode Vocabulary
- `live_microcap`
- `live_notrade`
- `paper_smoke`
- `paper_notrade`
- `testnet_smoke`
- `testnet_notrade`

## Catalog Layout
- `config/strategy_catalog/catalog_v1.json`
  - approved bundles
  - default risk envelope by mode
  - naming contract reference
- `config/strategy_catalog/templates/controller_template.yml`
- `config/strategy_catalog/templates/script_template.yml`

## Promotion Rules
Any new strategy variant must provide:
1. Controller + script config pair using the naming convention.
2. Risk envelope declaration mapped in catalog metadata.
3. Evidence from gates/reports before live promotion:
   - `reports/promotion_gates/latest.json`
   - `reports/reconciliation/latest.json`
   - `reports/parity/latest.json`
   - `reports/portfolio_risk/latest.json`

## Operator Workflow (No Compose Edits)
1. Add/update shared controller code in `controllers/` only.
2. Copy templates from `config/strategy_catalog/templates/`.
3. Create bot-specific config pair in:
   - `data/<bot>/conf/controllers/`
   - `data/<bot>/conf/scripts/`
4. Start with script conf:
   - `start --script v2_with_controllers.py --conf <script_config_name>.yml`
5. Collect gate evidence and update progress docs.

## Day 29 Done Contract
- New strategy onboarding is config-driven.
- Compose file stays unchanged for strategy additions.
- Approved bundles and defaults are centrally documented in catalog metadata.
