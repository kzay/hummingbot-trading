## Why

The `hbot/` project root mixes seven distinct concerns in a flat layout: source code, runtime data, generated reports, web app dependencies, infra configs, screenshots/Playwright artifacts, and an accidental nested directory. This makes the project hard to navigate, confuses IDE indexing (300+ `node_modules` dirs at root), creates accidental directories in Docker (`hbot/hbot/`), and violates the principle that project structure should communicate intent. The backtesting package also had a 289-line adapter factory that makes adding new strategies unnecessarily tedious.

## What Changes

**Track A (safe cleanup + internal refactors — completed in this change):**
- Fix hardcoded `hbot/`-prefixed default paths across all backtesting code, scripts, and the backtest API that create an accidental `hbot/hbot/` nested directory inside Docker containers. Safely inspect and remove the accidental directory after fixing defaults.
- Extract a declarative adapter registry from the 289-line `_build_adapter()` if/elif chain in the backtesting harness, preserving existing per-adapter hydration behavior.
- Add `data/README.md` documenting what is checked into git vs generated at runtime.
- Relocate root-level `node_modules/` and `package.json` (Playwright only) into `apps/realtime_ui_v2/` where they belong.

**Infra consolidation (completed — same initiative, now landed):**
- `compose/` → `infra/compose/`
- `monitoring/` → `infra/monitoring/`
- `env/` → `infra/env/`
- `security/` → consolidated into `infra/firewall-rules.sh` (host firewall helper; not a full `infra/security/` tree)
- Top-level `models/` removed — ML artifacts use `data/ml/models/` (see `README.md` and `ML_MODEL_URI`)
- `third_party/` → `docs/legal/`
- Top-level `backups/` removed — Postgres backups use `scripts/ops/pg_backup.py` and `reports/ops/`; event-store archives use host paths outside the repo

`config/` stays at `hbot/` root — it is runtime application input consumed by services and controllers, not purely ops config. Moving it would force container path churn with little architectural benefit.

## Capabilities

### New Capabilities
- `path-defaults-fix`: Fix cwd-relative path defaults across 20+ Python files (backtesting, scripts, analysis, ML, API) and 46+ YAML configs. Covers `types.py`, `config_loader.py`, `harness_cli.py`, `replay_harness.py`, `csv_importer.py`, `backtest_api.py`, `sweep_cli.py`, `list_data.py`, `fetch_historical_ohlcv.py`, `run_backtest_v2.py`, `run_fill_preset_sweep.py`, `run_sweep.py`, `run_walkforward.py`, `bot1_paper_day_summary.py`, `bot1_tca_report.py`, `bot1_performance_report.py`, `ftui_dashboard.py`, `build_regime_dataset.py`, `build_adverse_fill_dataset.py`, `train_regime_classifier.py`, `train_adverse_classifier.py`, `test_replay_harness.py`. Safely inspect and remove the accidental `hbot/hbot/` nested directory.
- `adapter-registry`: Extract a declarative adapter registry from `harness.py` `_build_adapter()` with behavior-preserving hydration covering all 10 adapter modes.
- `data-readme`: Add `data/README.md` explaining tracked vs generated contents.
- `node-relocation`: Move root-level Playwright `package.json` and `node_modules/` into `apps/realtime_ui_v2/`.
- `infra-consolidation`: **Done.** Compose, monitoring, and env live under `infra/`; firewall rules script at `infra/firewall-rules.sh`; docs and scripts reference `infra/env/.env`, `infra/compose/docker-compose.yml`, and `infra/monitoring/`. `config/` stays at root.

### Modified Capabilities

## Impact

**Track A (this change):**
- **Backtesting code**: `types.py`, `config_loader.py`, `harness_cli.py`, `replay_harness.py`, `csv_importer.py` — default path strings change from `hbot/data/historical` to `data/historical` and `hbot/reports/backtest` to `reports/backtest`.
- **Backtest API**: `backtest_api.py` — fallback paths for presets, reports, and job DB updated.
- **Scripts**: `list_data.py`, `fetch_historical_ohlcv.py`, `run_backtest_v2.py` — default args and docstrings updated.
- **YAML configs**: 46 backtest config files in `data/backtest_configs/` — `catalog_dir` and `output_dir` prefixes removed.
- **Backtesting harness**: `harness.py` `_build_adapter()` reduced from 289 to 20 lines via delegation to `adapter_registry.py`.
- **Node.js**: Root `package.json`, `package-lock.json`, `node_modules/` removed; `playwright` added to `apps/realtime_ui_v2/package.json` devDependencies.
- **`.gitignore`**: `node_modules/` entry added.

**Infra consolidation (done):**
- **Docker Compose**: `infra/compose/docker-compose.yml`; env file `infra/env/.env` (template `infra/env/.env.template`).
- **Monitoring**: Prometheus, Grafana, Loki, Alertmanager under `infra/monitoring/`.
- **Shell/Python scripts, Cursor rules, docs**: reference `infra/` paths (see `hbot/docs/ops/runbooks.md`, `.cursor/rules/project-context.mdc`).
