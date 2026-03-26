## ADDED Requirements

### Requirement: No service `main.py` exceeds 800 lines
After decomposition, every `services/*/main.py` SHALL be under 800 lines.

#### Scenario: Line count check
- **WHEN** `wc -l services/*/main.py` is run
- **THEN** every file SHALL report fewer than 800 lines

### Requirement: `paper_exchange_service/main.py` decomposed
The 3,529-line `paper_exchange_service/main.py` SHALL be split into:
- `main.py` — FastAPI/service wiring and startup (~300 lines)
- `protocol_handlers.py` — WebSocket and REST protocol handling
- `lifecycle.py` — service lifecycle, health checks, graceful shutdown
- `position_reconciler.py` — position reconciliation logic

#### Scenario: Service still starts correctly
- **WHEN** the paper exchange service Docker container is started
- **THEN** it SHALL pass its health check within 60 seconds

### Requirement: `ops_db_writer/main.py` decomposed
The 2,006-line `ops_db_writer/main.py` SHALL be split into logical modules within its package.

#### Scenario: No regression
- **WHEN** `test_ops_db_writer` tests (if any) are run
- **THEN** all SHALL pass

### Requirement: `bot_metrics_exporter.py` moved into a package
The 1,899-line `services/bot_metrics_exporter.py` (root-level single file) SHALL be moved to `services/bot_metrics_exporter/` as a package with its `sys.path` hack removed.

#### Scenario: Clean import
- **WHEN** `from services.bot_metrics_exporter import main` is run
- **THEN** it SHALL succeed without `sys.path` manipulation

### Requirement: `realtime_ui_api/` cleaned up
The realtime UI API's 4 files (1,438 + 1,730 + 1,584 + 708 = 5,460 lines total) SHALL have clearer separation:
- `main.py` — FastAPI app, WebSocket handlers
- `rest_routes.py` — REST endpoint handlers
- `data_readers.py` — log/fill/state reading logic (replaces `fallback_readers.py`)
- `backtest_api.py` — backtest-specific endpoints (already separate, keep)

#### Scenario: API endpoints still work
- **WHEN** the realtime UI API tests are run
- **THEN** all 1,793 lines of `test_realtime_ui_api.py` SHALL pass
