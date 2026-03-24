## ADDED Requirements

### Requirement: hb_bridge.py decomposed into focused modules
The 2,655-line `hb_bridge.py` SHALL be split into modules under `simulation/bridge/`:

- `event_router.py` — HB event translation, order/trade/position event firing
- `subscriber_manager.py` — subscriber registration, lifecycle hooks, event dispatch
- `connector_patches.py` — HB connector monkey-patches for paper mode
- `signal_handler.py` — external signal consumption, HARD_STOP handling

#### Scenario: No file exceeds 800 lines
- **WHEN** `wc -l simulation/bridge/*.py` is run
- **THEN** every file SHALL report fewer than 800 lines

#### Scenario: Public API preserved
- **WHEN** code uses `from simulation.hb_bridge import PaperDeskBridge`
- **THEN** the import SHALL succeed (via `simulation/bridge/__init__.py` re-export)

### Requirement: Only bridge modules import hummingbot
Within `hbot/simulation/`, only files under `simulation/bridge/` SHALL import from `hummingbot.*`. All other simulation modules SHALL remain HB-agnostic.

#### Scenario: HB import boundary
- **WHEN** `grep -r "from hummingbot\|import hummingbot" hbot/simulation/` is run excluding `simulation/bridge/`
- **THEN** zero matches SHALL be returned

### Requirement: Signal handler decoupled from bridge core
Signal consumption (Redis external signals, HARD_STOP) SHALL be a separate module that the bridge optionally composes, not embedded in the bridge's event loop.

#### Scenario: Signal handler independently testable
- **WHEN** `signal_handler.py` is imported in isolation
- **THEN** it SHALL NOT require a running HB connector or PaperDesk instance to import
