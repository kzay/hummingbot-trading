## ADDED Requirements

### Requirement: Single shim location at `controllers/hb_loader_shims/`
All Hummingbot controller-loader compatibility files SHALL reside under `controllers/hb_loader_shims/` with sub-folders matching HB's `controller_type` resolution:
- `hb_loader_shims/market_making/` — MM controller entrypoints
- `hb_loader_shims/directional/` — Directional controller entrypoints

#### Scenario: Market-making shims exist
- **WHEN** HB attempts to load `market_making.epp_v2_4`
- **THEN** `controllers/hb_loader_shims/market_making/epp_v2_4.py` SHALL resolve to `EppV24Controller`

#### Scenario: Directional shims exist
- **WHEN** HB attempts to load `directional.bot7_pullback_v1`
- **THEN** `controllers/hb_loader_shims/directional/bot7_pullback_v1.py` SHALL resolve to the bot7 pullback controller

### Requirement: Root-level wrapper files removed
After shim consolidation, the following root-level files SHALL NOT exist:
- `controllers/epp_v2_4_bot1.py`, `epp_v2_4_bot5.py`, `epp_v2_4_bot6.py`, `epp_v2_4_bot7.py`, `epp_v2_4_bot7_pullback.py`
- `controllers/bot1_baseline_v1.py`, `bot5_ift_jota_v1.py`, `bot6_cvd_divergence_v1.py`, `bot7_pullback_v1.py`
- `controllers/shared_mm_v24.py`

#### Scenario: No leftover wrappers at root
- **WHEN** `ls controllers/*.py` is run
- **THEN** no bot-specific wrapper or alias files SHALL appear — only core modules

### Requirement: Old `directional/` and `market_making/` directories replaced
`controllers/directional/` and `controllers/market_making/` (currently containing one-liner shims) SHALL be replaced by `controllers/hb_loader_shims/directional/` and `controllers/hb_loader_shims/market_making/`.

#### Scenario: Old directories removed
- **WHEN** the refactoring is complete
- **THEN** `controllers/directional/` and `controllers/market_making/` (the old locations) SHALL NOT exist

### Requirement: Shim documentation
A `controllers/hb_loader_shims/README.md` SHALL explain:
- Why these files exist (HB controller resolution mechanism)
- How to add a new shim for a new strategy
- Which YAML config fields correspond to which shim paths

#### Scenario: README exists and is informative
- **WHEN** `controllers/hb_loader_shims/README.md` is read
- **THEN** it SHALL contain sections on purpose, adding new shims, and YAML mapping

### Requirement: YAML controller_name strings unchanged
No YAML config file's `controller_name` or `controller_type` field SHALL be modified by this refactoring.

#### Scenario: Config compatibility preserved
- **WHEN** all `data/bot*/conf/**/*.yml` files are compared before and after
- **THEN** `controller_name` and `controller_type` values SHALL be identical
