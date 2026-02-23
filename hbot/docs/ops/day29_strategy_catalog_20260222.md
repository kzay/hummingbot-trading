# Day 29 - Strategy/Controller Modularization v1

## Scope
- Introduce a formal strategy catalog and config templates to make rollout config-driven.
- Keep strategy onboarding independent from compose changes.

## Delivered
- Catalog doc:
  - `docs/ops/strategy_catalog_v1.md`
- Catalog metadata:
  - `config/strategy_catalog/catalog_v1.json`
- Config templates:
  - `config/strategy_catalog/templates/controller_template.yml`
  - `config/strategy_catalog/templates/script_template.yml`
- Runbook update:
  - `docs/ops/runbooks.md` (`Strategy Catalog Operations` section)

## Validation
- Catalog references current known bundles (`bot1`, `bot3`, `bot4`) and risk envelopes by mode.
- Runbook now defines a no-compose-edit workflow for adding variants.

## Outcome
- Strategy/controller modularization is now documented and operationalized as a config-first workflow.
- Adding a new variant requires shared code update + template-based config pair only.
