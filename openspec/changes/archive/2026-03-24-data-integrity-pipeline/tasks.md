## 1. Catalog Integrity (data_catalog.py + data_store.py)

- [x] 1.1 Add `sha256` field to `DataCatalog.register()`: compute SHA-256 hash of the parquet file at `file_path` and include it in the catalog entry dict. Use `hashlib.sha256` with chunked file reading (8KB chunks).
- [x] 1.2 Add `verify_entry(entry) -> list[str]` method to `DataCatalog`: check file existence, file size match against `file_size_bytes`, SHA-256 match against `sha256` (skip if field missing, log warning), parquet metadata row count match against `row_count` (use pandas `read_parquet` with `columns=[]`).
- [x] 1.3 Add `verify_all() -> dict[str, list[str]]` method to `DataCatalog`: iterate all entries, call `verify_entry()`, return dict mapping `"{exchange}/{pair}/{resolution}"` to warning lists.
- [x] 1.4 Add `reconcile_disk(base_dir) -> dict` method to `DataCatalog`: walk `base_dir` for `data.parquet` files, compare against catalog entries, return `{"orphans": [...], "stale": [...]}`.
- [x] 1.5 Add `scan_gaps(candles, expected_interval_ms) -> list[tuple[int, int]]` function to `data_store.py`: iterate sorted candle timestamps, return list of `(gap_start_ms, gap_end_ms)` tuples where the gap exceeds `expected_interval_ms * 1.5`.
- [x] 1.6 Write tests for `verify_entry`, `verify_all`, `reconcile_disk` in `tests/controllers/test_backtesting/test_data_catalog_integrity.py`. Write tests for `scan_gaps` in `tests/controllers/test_backtesting/test_data_store_gaps.py`.

## 2. Data Requirements Manifest

- [x] 2.1 Create `config/data_requirements.yml` with entries for `ml_feature_service`, `backtesting`, `ml_training`, and `strategy_controller`. Use `required_lookback_bars`, `bootstrap_from` and/or `retention_policy`, `canonical_datasets`, optional `materialized_datasets`, pairs, exchange, and `derived_from`. Include research-side canonical datasets `mark_1m`, `index_1m`, `funding`, and `ls_ratio`.
- [x] 2.2 Create `controllers/backtesting/data_requirements.py` with a `load_manifest(path) -> dict` function that parses the YAML manifest and a `compute_refresh_scope(manifest) -> dict` function that returns the union of pairs, canonical datasets to fetch, materialized datasets to build locally, and bootstrap/retention policy.
- [x] 2.3 Write tests in `tests/controllers/test_backtesting/test_data_requirements.py`: test manifest parsing, union computation, missing manifest fallback, invalid YAML handling.

## 3. Data Change Notification (stream + publisher)

- [x] 3.1 Add `DATA_CATALOG_STREAM = "hb.data_catalog.v1"` to `platform_lib/contracts/stream_names.py` and add it to `STREAM_RETENTION_MAXLEN` with default maxlen 1000.
- [x] 3.2 Create `controllers/backtesting/data_catalog_events.py` with a `publish_catalog_update(redis_client, exchange, pair, resolution, start_ms, end_ms, row_count, gaps_found, gaps_repaired)` function that publishes a JSON event to `hb.data_catalog.v1` via `XADD`.
- [x] 3.3 Write tests in `tests/controllers/test_backtesting/test_data_catalog_events.py`: test event payload format, test no publish on None redis client.

## 4. Data Refresh Script (scripts/ops/data_refresh.py)

- [x] 4.1 Create `scripts/ops/data_refresh.py` with a `main()` entry point. Read config first from `config/data_requirements.yml` via `compute_refresh_scope()`, fall back to env vars: `DATA_REFRESH_EXCHANGE`, `DATA_REFRESH_PAIRS`, `DATA_REFRESH_DATASETS`, `BACKTEST_CATALOG_DIR`.
- [x] 4.2 Implement incremental download loop for canonical datasets only: fetch `1m`, `mark_1m`, `index_1m`, `funding`, and `ls_ratio` from the exchange according to manifest scope and bootstrap/retention policy.
- [x] 4.3 Implement gap detection pass: after each incremental download, load the parquet via `load_candles()`, call `scan_gaps()`, log gap count and total missing minutes.
- [x] 4.4 Implement gap backfill: for each detected gap `(start_ms, end_ms)`, call `DataDownloader.download_candles()` for that range, merge into the existing parquet (dedup by timestamp_ms), re-validate, re-save, re-register.
- [x] 4.5 Implement higher-timeframe materialization: derive `5m`, `15m`, and `1h` parquet datasets from canonical `1m` after refresh/backfill, register them in the catalog, and avoid direct exchange downloads for those resolutions.
- [x] 4.6 Implement integrity check pass: call `catalog.verify_all()` and `catalog.reconcile_disk()` after all downloads/materializations, log warnings at WARNING level.
- [x] 4.7 After each successful dataset update, call `publish_catalog_update()` to emit a `DataCatalogEvent` to Redis.
- [x] 4.8 Add `--dry-run` flag that reports what would be downloaded/repaired/materialized without making changes.
- [x] 4.9 Write smoke test in `tests/scripts/test_data_refresh.py` that mocks `DataDownloader` and verifies the refresh loop logic including event publication and higher-timeframe materialization.

## 5. ops-scheduler Integration

- [x] 5.1 Add a new job entry to `JOBS` list in `services/ops_scheduler/main.py`: name `data-refresh`, command runs `scripts/ops/data_refresh.py`, interval env var `DATA_REFRESH_INTERVAL_SEC`, default 21600 (6 hours).
- [x] 5.2 Add `DATA_REFRESH_*` and `BACKTEST_CATALOG_DIR` env vars to the `ops-scheduler` service in `infra/compose/docker-compose.yml`, using `DATA_REFRESH_DATASETS` for canonical dataset selection.

## 6. ML Feature Service — Parquet Seeding + Hot-Reload (main.py + pair_state.py)

- [x] 6.1 In `pair_state.py`: make `ROLLING_WINDOW` configurable — read from `ML_ROLLING_WINDOW` env var (default `20160`). Change the module-level constant to use `int(os.getenv("ML_ROLLING_WINDOW", "20160"))`.
- [x] 6.2 In `main.py`: add `HISTORICAL_DATA_DIR` env var (default `data/historical`).
- [x] 6.3 In `main.py`: add `_seed_from_parquet(pair, exchange, base_dir, max_bars) -> pd.DataFrame | None` function. Uses `resolve_data_path(exchange, pair, "1m", base_dir)` to find the file, reads it with pandas, returns the tail `max_bars` rows. Returns `None` on any error (missing file, corrupt, etc.) with a warning log.
- [x] 6.4 In `main.py`: modify the startup seeding section to implement parquet-first flow: (1) try `_seed_from_parquet()`, (2) if parquet found, determine the gap from `parquet_last_ts - 5min` to now, fetch that gap via the existing API code, (3) concatenate + dedup by `timestamp_ms` + sort, (4) seed `PairFeatureState`. Fall back to API-only if no parquet.
- [x] 6.5 Update `ML_WARMUP_BARS` default from `1440` to `20160` to match the new rolling window.
- [x] 6.6 Add manifest-based startup validation: read `config/data_requirements.yml`, compare seeded bar count against `ml_feature_service.required_lookback_bars`, log whether coverage is sufficient or partial.
- [x] 6.7 Add data catalog stream subscription to main loop: subscribe to `hb.data_catalog.v1`, on receiving `data_catalog_updated` events matching configured pair + `1m` resolution, stage a safe refresh.
- [x] 6.8 Implement safe rolling-window rebuild on staged refresh: re-read parquet tail, combine with currently retained live bars, rebuild the deque from the sorted unique union, keep the newest `ML_ROLLING_WINDOW` bars, and preserve current live continuity.
- [x] 6.9 Add fallback periodic parquet freshness check: every `ML_REFRESH_INTERVAL_S`, check if parquet's last bar is newer than last loaded, re-read if so (covers missed Redis events).
- [x] 6.10 Write tests in `tests/services/test_ml_feature_service/test_parquet_seeding.py`: test parquet-found path, parquet-missing fallback, parquet+API bridge dedup, corrupt parquet graceful degradation, hot-reload from catalog event, safe rebuild preserving newest live bars, manifest validation logging.

## 7. Docker Compose Wiring

- [x] 7.1 Add env vars to `ml-feature-service` in `docker-compose.yml`: `HISTORICAL_DATA_DIR`, `ML_ROLLING_WINDOW`.
- [x] 7.2 Add env vars to `ops-scheduler` in `docker-compose.yml`: `DATA_REFRESH_EXCHANGE`, `DATA_REFRESH_PAIRS`, `DATA_REFRESH_RESOLUTIONS`, `DATA_REFRESH_INTERVAL_SEC`, `BACKTEST_CATALOG_DIR`.
- [x] 7.3 Update `infra/env/.env.template` with documented entries for all new env vars.

## 8. Validation and Smoke Test

- [x] 8.1 Run `python -m py_compile` on all new/modified files to verify syntax.
- [x] 8.2 Run `PYTHONPATH=hbot python -m pytest` on all new test files to verify they pass.
- [x] 8.3 Docker smoke test: `docker compose up -d ops-scheduler ml-feature-service`, verify ml-feature-service logs show "Seeded N bars from parquet" with N close to 20160, verify ops-scheduler logs show data-refresh job registered.
- [x] 8.4 Run the existing architecture contract tests: `PYTHONPATH=hbot python -m pytest hbot/tests/architecture/ -q`.
- [x] 8.5 Verify canonical/materialized consistency: trigger a manual refresh, then confirm locally materialized `5m`/`15m`/`1h` bars match resampling from canonical `1m`.
- [x] 8.6 Verify the data catalog stream integration: trigger a manual data refresh, confirm `hb.data_catalog.v1` event appears in Redis, confirm ml-feature-service logs show safe hot-reload.
