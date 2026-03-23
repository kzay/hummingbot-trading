## ADDED Requirements

### Requirement: Backtesting path defaults assume cwd is `hbot/`
All default path values in backtesting config dataclasses, config loaders, scripts, and API services SHALL use paths relative to `hbot/` (e.g., `data/historical`, `reports/backtest`) without an `hbot/` prefix. This prevents creating accidental `hbot/hbot/` nested directories when the working directory is already `hbot/`.

#### Scenario: DataSourceConfig default catalog_dir
- **WHEN** a `DataSourceConfig` is created with default values
- **THEN** `catalog_dir` equals `"data/historical"` (not `"hbot/data/historical"`)

#### Scenario: BacktestConfig default output_dir
- **WHEN** a `BacktestConfig` is created with default values
- **THEN** `output_dir` equals `"reports/backtest"` (not `"hbot/reports/backtest"`)

#### Scenario: config_loader.py defaults match types.py
- **WHEN** `load_backtest_config()` parses a YAML file that omits `catalog_dir` and `output_dir`
- **THEN** the resulting config uses `"data/historical"` and `"reports/backtest"` as defaults

#### Scenario: harness_cli.py fallback paths
- **WHEN** `harness_cli.py` resolves the data catalog directory
- **THEN** it checks `"data/historical"` first, falling back to `"hbot/data/historical"` only as a legacy path

#### Scenario: replay_harness.py defaults
- **WHEN** a `ReplayDataConfig` is created with defaults
- **THEN** `catalog_dir` equals `"data/historical"`

#### Scenario: csv_importer.py default catalog_dir
- **WHEN** `import_and_register()` is called without specifying `catalog_dir`
- **THEN** the default is `"data/historical"`

#### Scenario: backtest_api.py fallback paths
- **WHEN** the backtest API resolves preset, report, and DB paths without env vars
- **THEN** defaults are `"data/backtest_configs"`, `"reports/backtest/jobs"`, and `"data/backtest_jobs.sqlite3"`

#### Scenario: Script CLI defaults
- **WHEN** `list_data.py` or `fetch_historical_ohlcv.py` is invoked without `--dir`/`--output`
- **THEN** the default path is `"data/historical"`

### Requirement: Safe `hbot/hbot/` cleanup
The `hbot/hbot/` directory SHALL be inspected before deletion. Only delete after confirming it contains purely generated artifacts. If unexpected content is found, log a warning and skip deletion.

#### Scenario: Docker backtest run after fix
- **WHEN** a backtest runs inside a Docker container with cwd `/workspace/hbot`
- **THEN** output files are written to `/workspace/hbot/reports/backtest/`, not `/workspace/hbot/hbot/reports/backtest/`

#### Scenario: Inspect before delete
- **WHEN** `hbot/hbot/` exists
- **THEN** its contents are listed and inspected before any deletion occurs

### Requirement: YAML configs use cwd-relative paths
Backtest YAML configs in `data/backtest_configs/` SHALL NOT hardcode `hbot/` prefixes in `catalog_dir` or `output_dir` fields.

#### Scenario: YAML config catalog_dir
- **WHEN** a backtest YAML config specifies `catalog_dir`
- **THEN** the value does not start with `hbot/`

### Requirement: Tests validate new defaults
Tests that assert path default values SHALL be updated to expect the new cwd-relative defaults.

#### Scenario: harness_cli legacy fallback test
- **WHEN** `test_prefers_hbot_nested_when_only_that_exists` runs
- **THEN** it validates that `hbot/data/historical` is used as a fallback when only that path exists on disk
