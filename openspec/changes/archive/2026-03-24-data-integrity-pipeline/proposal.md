## Why

Three fundamental data integrity problems block the trading desk from operating at semi-pro grade:

1. **No centralized data requirements**: Each consumer (ML feature service, backtesting, ML training, strategy controller) independently hardcodes its own lookback (10,080 bars for features, 60 for backtest warmup, 1,000+ for training). There is no single manifest declaring what data is needed, so the refresh pipeline doesn't know what to download or how far back.

2. **No change notification**: When historical data is refreshed (gaps filled, new bars appended), no consumer is notified. The ML feature service seeds once at startup and never re-reads. Backtesting and research re-read catalog.json per run but have no way to know data improved since the last run.

3. **Disconnected data flow**: The 639K+ row parquet store, the live ML feature service, the backtesting harness, and ML training all operate independently. The ML service ignores the parquet store entirely (fetching only 1,440 bars from the API), the feature pipeline's `atr_pctl_7d` (10,080-bar lookback) is permanently NaN, and the historical store has no automated refresh, gap repair, or integrity verification.

For a semi-pro desk, data integrity is non-negotiable: stale data means wrong features, wrong features mean wrong signals, wrong signals mean real losses.

## What Changes

- **ML feature service seeds from local parquet first**, bridging only the gap between parquet's last bar and now via exchange API — startup goes from 1,440 bars to 20,160 bars (14 days) instantly from disk.
- **Rolling window expanded** from 1,440 to 20,160 bars (configurable) so the feature pipeline produces valid values for all indicators including 7-day lookbacks.
- **Automated incremental data refresh** via a new ops-scheduler job that runs every 6 hours, fetching canonical datasets (`1m`, `mark_1m`, `index_1m`, `funding`, `ls_ratio`) and materializing higher timeframes locally.
- **Gap detection and repair** scans parquet files for missing bars and backfills from the exchange API.
- **Catalog integrity verification** adds SHA-256 checksums to `catalog.json`, with periodic verification that files exist, sizes match, and hashes are correct.
- **All consumers benefit**: backtesting, ML training/research, and the live ML feature service all read from the same continuously-validated parquet store.
- **Data requirements manifest** centralizes what each consumer needs (required lookback, bootstrap/retention policy, canonical datasets, derived datasets, pairs) so the refresh pipeline knows exactly what to fetch and what to materialize.
- **Data catalog event stream** (`hb.data_catalog.v1`) notifies consumers when historical data changes, enabling the ML feature service to hot-reload its seed without restart.

## Capabilities

### New Capabilities
- `data-requirements-manifest`: Centralized YAML manifest declaring per-consumer data lookback requirements, used by the refresh pipeline to determine download scope and by consumers to self-validate their data coverage.
- `data-change-notification`: Redis stream event published after each catalog mutation, enabling consumers to react to new or repaired data without restart.
- `data-refresh-scheduler`: Automated periodic incremental download of new candle data, with gap scanning and backfill, integrated into the ops-scheduler.
- `catalog-integrity`: SHA-256 checksums in catalog entries, periodic verification of file existence/size/hash, disk reconciliation for orphan and stale entries.
- `ml-parquet-seeding`: ML feature service reads historical parquet at startup, bridges the gap to live data via API, operates with a configurable 14-day rolling window, and hot-reloads when notified of data updates.

### Modified Capabilities

## Impact

- **services/ml_feature_service/main.py**: New `_seed_from_parquet()` function, modified `_seed_pair()` flow (parquet-first, API-bridge, API-fallback).
- **services/ml_feature_service/pair_state.py**: `ROLLING_WINDOW` increased from 1,440 to 20,160, configurable via env var.
- **services/ops_scheduler/main.py**: New `data-refresh` job entry.
- **controllers/backtesting/data_store.py**: New `scan_gaps()` function.
- **controllers/backtesting/data_catalog.py**: New `sha256` field, `verify_entry()`, `verify_all()`, `reconcile_disk()` methods.
- **scripts/ops/data_refresh.py**: New standalone script for incremental download + gap repair + integrity check.
- **infra/compose/docker-compose.yml**: New env vars for ops-scheduler (`DATA_REFRESH_*`) and ml-feature-service (`HISTORICAL_DATA_DIR`, `ML_ROLLING_WINDOW`).
- **Memory impact**: ML feature service memory increases from ~1,440 bars to ~20,160 bars per pair (~10x). Still well within the 1GB container limit (~20K bars * 6 floats * 8 bytes = ~1MB per pair).
- **platform_lib/contracts/stream_names.py**: New `DATA_CATALOG_STREAM = "hb.data_catalog.v1"` constant.
- **config/data_requirements.yml**: New manifest declaring per-consumer lookback, resolution, and pair requirements.
- **Dependencies**: No new external dependencies. Uses existing `ccxt`, `pandas`, `hashlib` (stdlib), `redis`, `pyyaml`.
