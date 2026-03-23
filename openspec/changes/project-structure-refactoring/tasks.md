## 1. Fix Backtesting Path Defaults (path-defaults-fix)

- [x] 1.1 Change `DataSourceConfig.catalog_dir` default from `"hbot/data/historical"` to `"data/historical"` in `controllers/backtesting/types.py`
- [x] 1.2 Change `BacktestConfig.output_dir` default from `"hbot/reports/backtest"` to `"reports/backtest"` in `controllers/backtesting/types.py`
- [x] 1.3 Update `config_loader.py` defaults to match: `catalog_dir` → `"data/historical"`, `output_dir` → `"reports/backtest"`
- [x] 1.4 Update `harness_cli.py` `_parse_config()` `output_dir` default from `"hbot/reports/backtest"` to `"reports/backtest"`
- [x] 1.5 Update `harness_cli.py` docstring to reflect new fallback chain
- [x] 1.6 Grep `data/backtest_configs/*.yml` for any hardcoded `hbot/` path prefixes in `catalog_dir` or `output_dir` and fix them (46 files)
- [x] 1.7 Update `replay_harness.py` `ReplayDataConfig.catalog_dir` default and loader default
- [x] 1.8 Update `csv_importer.py` `import_and_register()` `catalog_dir` default
- [x] 1.9 Update `backtest_api.py` fallback paths for `_PRESETS_DIR`, `_REPORTS_DIR`, `_DB_PATH`
- [x] 1.10 Update `list_data.py` docstring and `--dir` default
- [x] 1.11 Update `fetch_historical_ohlcv.py` docstring, `output_dir` parameter default, and `--output` argparse default
- [x] 1.12 Update `run_backtest_v2.py` docstring examples
- [x] 1.13 Update `sweep_cli.py` default output path
- [x] 1.14 Update `test_replay_harness.py` fixture output_dir value
- [x] 1.15 Update ML scripts: `build_regime_dataset.py`, `build_adverse_fill_dataset.py`, `train_regime_classifier.py`, `train_adverse_classifier.py` — defaults and docstrings
- [x] 1.16 Update analysis scripts: `bot1_paper_day_summary.py`, `bot1_tca_report.py`, `bot1_performance_report.py`, `ftui_dashboard.py` — defaults and docstrings
- [x] 1.17 Update backtest CLI docstrings: `run_fill_preset_sweep.py`, `run_sweep.py`, `run_walkforward.py`
- [x] 1.18 Update YAML config comments: `bot7_pullback.yml`, `bot7_pullback_v2.yml`, `bot7_pullback_replay.yml`, `bot7_pullback_sweep.yml`, `bot1_baseline.yml`
- [x] 1.19 Inspect `hbot/hbot/` contents — only delete if it contains purely generated artifacts; warn and skip if unexpected content found
- [x] 1.20 Annotate experiment ledger entry about path direction reversal
- [x] 1.21 Compile all changed files and run backtesting tests

## 2. Extract Adapter Registry (adapter-registry)

- [x] 2.1 Create `controllers/backtesting/adapter_registry.py` with `AdapterEntry` dataclass and `ADAPTER_REGISTRY` dict for all 10 adapter modes (9 in registry + 1 standalone runtime entry)
- [x] 2.2 Implement `hydrate_config()` function with two paths: explicit type lists and introspection, both with safe boolean handling (`_safe_bool()` guard)
- [x] 2.3 Implement `build_adapter()` function that looks up registry, lazy-imports adapter module, hydrates config, and instantiates adapter
- [x] 2.4 Handle `"runtime"` mode via `_build_runtime_adapter()` with strategy loading, delegating config hydration to `hydrate_config()` via `_RUNTIME_ENTRY`
- [x] 2.5 Replace `_build_adapter()` in `harness.py` with delegation to `adapter_registry.build_adapter()`
- [x] 2.6 Verify `_build_adapter()` is now < 50 lines (actual: 20 lines)
- [x] 2.7 Run all backtesting tests (`test_backtesting/`) to confirm no behavior change

## 3. Add data/README.md (data-readme)

- [x] 3.1 Create `data/README.md` documenting tracked content (`bot{1..7}/conf/`, `backtest_configs/`, `historical/catalog.json`)
- [x] 3.2 Document generated/gitignored content (`bot{1..7}/logs/`, `bot{1..7}/data/`, `historical/bitget/`, `shared/`, `ml/`, `backtest_jobs.sqlite3`)

## 4. Relocate Node.js Dependencies (node-relocation)

- [x] 4.1 Add `"playwright": "^1.58.2"` to `apps/realtime_ui_v2/package.json` devDependencies
- [x] 4.2 Delete `hbot/package.json` and `hbot/package-lock.json`
- [x] 4.3 Delete `hbot/node_modules/` directory
- [x] 4.4 Add `node_modules/` to `hbot/.gitignore`
- [x] 4.5 Run `npm install` from `apps/realtime_ui_v2/` to verify `playwright` resolves
- [x] 4.6 Verify `screenshot-dashboard.js` can import `playwright` from app directory

## 5. Consolidate Infra Directories (infra-consolidation) — DONE

**Status**: Implemented. VPS operators should still verify cron/systemd and any out-of-repo scripts point at `infra/` paths.

**Prerequisite task** (recommended for production hosts):
- [ ] 5.0 Audit VPS for cron jobs, systemd units, and manual scripts still referencing legacy `compose/`, `env/`, `monitoring/`, or `security/` paths

**Implementation tasks**:
- [x] 5.1 Create `infra/` directory at `hbot/` root
- [x] 5.2 `compose/` → `infra/compose/`
- [x] 5.3 `monitoring/` → `infra/monitoring/`
- [x] 5.4 `security/` → `infra/firewall-rules.sh` (consolidated script; not a full `infra/security/` tree)
- [x] 5.5 `env/` → `infra/env/`
- [x] 5.6 Update `docker-compose.yml` build contexts and volume mounts for new location
- [x] 5.8 Update shell scripts referencing `env/.env`, `compose/`, `monitoring/`
- [x] 5.9 Update Python scripts referencing compose/env paths
- [x] 5.10 Update `.cursor/rules/project-context.mdc` and `.cursor/rules/dashboard-deploy.mdc`
- [x] 5.11 Update `README.md`, `BACKLOG.md`, and `hbot/docs/**` path references
- [x] 5.12 Run `docker compose config` with `-f infra/compose/docker-compose.yml` to validate
- [ ] 5.13 One real `docker compose up -d` smoke test on target host (operator checklist)
- [ ] 5.14 Compile all changed Python files and run full test suite after any follow-up code changes

**Related cleanups (outside strict “infra dirs” list)**:
- [x] Remove top-level `models/`; document `data/ml/models/` for `ML_MODEL_URI`
- [x] `third_party/` → `docs/legal/`
- [x] Remove top-level `backups/`; backups via `pg_backup.py` / `reports/ops/` and external archive paths

**Note**: `config/` stays at `hbot/` root — it is runtime application input, not ops config.
