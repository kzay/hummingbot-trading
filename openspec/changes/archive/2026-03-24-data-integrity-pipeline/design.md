## Context

The trading desk operates BTC-USDT and ETH-USDT perpetual futures on Bitget. Four classes of consumers depend on historical candle data, each with different requirements:

| Consumer | Access pattern | Lookback needed | Resolution | Gap tolerance | Notification need |
|----------|---------------|----------------|------------|---------------|-------------------|
| ML feature service (live) | Tail N bars at startup, then stream | 10,080 bars min (7d), 20,160 ideal (14d) | 1m (resampled to 5m/15m/1h) | Zero — gaps produce NaN features | Hot-reload on data update |
| Backtesting / replay | Arbitrary date ranges, full scan | 60 bars warmup + full range | 1m, 5m, 15m, 1h | Warns but proceeds | Fresh on each run (re-reads catalog.json) |
| ML training / research | Large ranges for feature + model fitting | 1,000+ rows minimum, ideally full history | 1m, 5m, 15m, 1h, mark_1m, index_1m, funding, ls_ratio | Must be documented | Fresh on each CLI invocation |
| Strategy controller | EMA/ATR from price buffer | 55 bars seed (max(ema=50, atr=14)+5) | 1m (via candle API) | Tolerates gaps (price buffer forward-fills) | Not needed (uses live stream) |

**Current gaps (per investigation):**
1. No centralized manifest of what data each consumer needs — lookbacks are hardcoded in 4+ places
2. No notification mechanism when data changes — `DataCatalog` has no event emission
3. ML feature service ignores the parquet store entirely, fetching only 1,440 bars from the API
4. `PairFeatureState.ROLLING_WINDOW = 1440` means `atr_pctl_7d` (needs 10,080 bars) is always NaN

**Constraints:**
- Single VPS deployment (no distributed storage)
- Paper trading is primary environment; same data pipeline serves live
- `DataDownloader` already supports `resume_from_ms` and incremental merge+dedup
- `validate_candles()` already checks gaps, dupes, OHLC consistency, spikes
- Memory budget: 1GB per ML service container
- Existing Redis stream pattern: `hb.<domain>.v1` with JSON payload, `XADD` with `maxlen`

## Goals / Non-Goals

**Goals:**
- Every consumer gets gap-free, validated data from a single source of truth (parquet store)
- The parquet store stays current automatically (max 6h lag, configurable)
- Gaps are detected and repaired automatically during refresh cycles
- Data corruption is detectable via checksums
- ML feature service starts with 14 days of history from disk in <2 seconds, bridging to live via API
- All features (including `atr_pctl_7d` with 10,080-bar lookback) produce valid values from the first tick

**Non-Goals:**
- Real-time (sub-second) parquet updates — the 6h refresh cycle is sufficient; live data comes from the stream/API
- Multi-exchange or multi-venue data federation — only Bitget for now
- Replacing the realtime-ui market history provider — it has its own DB+stream+REST stack
- Tick-level (trade) or order book data in the refresh pipeline — candles and funding only
- Distributed storage, cloud sync, or replication
- Forcing all consumers to subscribe to the data catalog stream — notification is opt-in; batch consumers (backtesting, research) continue to re-read catalog.json per invocation

## Decisions

### D1: Parquet as canonical store (not Postgres, not Redis)

**Choice:** Keep parquet files as the single source of truth for historical data.

**Why not Postgres?** The access pattern is columnar analytical reads (load all OHLCV for date range). Parquet with Zstd compression is 5-10x more compact and 2-3x faster for full-scan reads than Postgres for this workload. Zero infrastructure overhead — files on disk, no daemon.

**Why not Redis?** Redis is appropriate for live streaming state, not for 1M+ row historical archives. Memory cost would be prohibitive.

**Alternative considered:** SQLite — decent for small datasets but parquet's columnar layout and compression are purpose-built for timeseries analytics. The existing `data_store.py` + `data_catalog.py` already implement the full lifecycle.

### D2: ops-scheduler job (not dedicated service)

**Choice:** Add a `data-refresh` job to the existing `ops_scheduler` service.

**Rationale:** Data refresh is periodic (default every 6h), not continuous. The ops-scheduler already runs 6 periodic jobs with fault-isolated threads. A dedicated Docker service for a 6-hourly batch job would be overengineered. The ops-scheduler has access to the same volume mounts and can run `DataDownloader` directly.

**Alternative considered:** Dedicated `data-refresh-service` container — rejected because it would add container overhead for something that runs for ~2 minutes every 6 hours.

### D3: Parquet-first seeding with API bridge for ML service

**Choice:** On startup, the ML feature service reads the tail of the parquet file (20,160 bars), then fetches only the gap from parquet's last timestamp to now via the exchange API.

**Rationale:**
- Reading 20K rows from a local parquet: ~50ms
- Fetching 20K rows from Bitget API (200 bars/request, 0.3s delay): ~30 seconds + rate limit risk
- The parquet file is always available (same Docker volume mount), so startup is instant and reliable
- The API bridge is a small fill (typically 0-360 bars for a 6h refresh cycle) that handles the staleness gap

**Sequence:** parquet tail → API bridge → concatenate + deduplicate → seed `PairFeatureState`

### D4: Rolling window = 20,160 bars (14 days), configurable

**Choice:** Increase `ROLLING_WINDOW` from 1,440 to 20,160, exposed as `ML_ROLLING_WINDOW` env var.

**Rationale:** The feature pipeline's longest lookback is `atr_pctl_7d` at `rolling(10080, min_periods=1440)`. A 14-day window provides 2x buffer so the 7-day rank has a full history to rank against. Memory cost is negligible: 20K bars * 6 floats * 8 bytes = ~1MB per pair.

**Why not unlimited?** A deque with no maxlen would grow unboundedly over weeks of uptime. 14 days is the sweet spot: covers all feature lookbacks with margin, and memory stays bounded.

### D5: SHA-256 at registration, verified at refresh

**Choice:** Compute SHA-256 of the parquet file at registration time, store in `catalog.json`, verify during the refresh cycle.

**Why SHA-256 over CRC32?** SHA-256 is cryptographically strong and detects bit-rot or silent corruption that CRC32 could miss. The performance difference is negligible for files under 50MB (our largest is 39MB).

**Alternative considered:** Parquet footer checksums — parquet already has page-level CRC but these only catch read-time corruption, not silent file replacement or truncation. The catalog-level hash covers the entire file.

### D6: Data requirements manifest (YAML, not hardcoded)

**Choice:** Create `config/data_requirements.yml` — a single YAML file declaring what every consumer needs.

**Structure:**
```yaml
consumers:
  ml_feature_service:
    required_lookback_bars: 20160
    bootstrap_from: "90d"
    canonical_datasets: ["1m"]
    pairs: ["BTC-USDT"]
    exchange: bitget
    derived_from: "feature_pipeline atr_pctl_7d = rolling(10080) * 2x buffer"

  backtesting:
    required_lookback_bars: 60
    retention_policy: "full_history"
    canonical_datasets: ["1m"]
    materialized_datasets: ["5m", "15m", "1h"]
    pairs: ["BTC-USDT", "ETH-USDT"]
    exchange: bitget
    warmup_bars: 60

  ml_training:
    required_lookback_bars: 1000
    retention_policy: "full_history"
    canonical_datasets: ["1m", "mark_1m", "index_1m", "funding", "ls_ratio"]
    materialized_datasets: ["5m", "15m", "1h"]
    pairs: ["BTC-USDT", "ETH-USDT"]
    exchange: bitget
    min_rows: 1000

  strategy_controller:
    required_lookback_bars: 60
    canonical_datasets: ["1m"]
    pairs: ["BTC-USDT"]
    exchange: bitget
    source: "live_stream"   # does not use parquet store
```

**Rationale:**
- The manifest separates the minimum working set (`required_lookback_bars`) from bootstrap and retention policy; this avoids the ambiguous `null = full history` behavior for initial downloads
- The data refresh script reads this manifest to determine download scope (union of pairs, canonical datasets to fetch from exchange, derived datasets to materialize locally)
- Each consumer can validate at startup: "do I have enough data for my declared requirements?"
- When a consumer's lookback changes (e.g., adding a 30-day feature), only one file needs updating — the refresh pipeline automatically adapts
- Derived-from field documents *why* a lookback is needed, preventing mystery numbers

**Why not env vars?** Env vars are fine for overrides, but the manifest captures the *relationships* between consumers and data — which env vars cannot express. The env var `ML_ROLLING_WINDOW` remains as a runtime override.

**Alternative considered:** Embedding requirements in each consumer's code and scraping them — fragile, requires running all consumers to discover requirements.

### D7: Data catalog change notification via Redis stream

**Choice:** After each successful refresh or materialization update, the **official data refresh pipeline** publishes a `DataCatalogEvent` to `hb.data_catalog.v1`. Other catalog writers (manual CLI downloads, CSV imports, research scripts) do **not** auto-publish; they may opt in via a `--notify` flag after validation passes.

**Why single publisher?** The refresh pipeline is the only writer that guarantees full integrity (validate, scan gaps, backfill, SHA-256) before emitting. Allowing unvalidated writes to trigger hot-reload would undermine the consumer trust contract. Manual writers update `catalog.json` (so batch consumers see changes on next run) but do not push to the stream unless explicitly requested.

**Event payload:**
```json
{
  "event_type": "data_catalog_updated",
  "producer": "data_refresh",
  "exchange": "bitget",
  "pair": "BTC-USDT",
  "resolution": "1m",
  "start_ms": 1735689600000,
  "end_ms": 1774051140000,
  "row_count": 639360,
  "gaps_found": 0,
  "gaps_repaired": 0,
  "timestamp_ms": 1774100000000
}
```

**Who publishes:** The data refresh script, after a successful incremental download + gap repair cycle.

**Who subscribes:**
- **ML feature service** (opt-in): listens for updates to its configured pairs. When notified, it performs a safe window rebuild from parquet plus retained live bars. This is a *hot-reload* — no restart needed.
- **Backtesting / research** (not subscribed): These are batch processes that construct a new `DataCatalog` per run, so they always see the latest catalog.json. No stream subscription needed.
- **Realtime UI API** (not subscribed): Uses its own Redis stream stack, not the parquet catalog.

**Why Redis stream (not filesystem polling)?**
- Consistent with the existing `hb.<domain>.v1` pattern (17 streams already defined)
- Sub-second latency vs. polling interval
- Consumer group semantics for at-least-once delivery
- No new infrastructure — Redis is already a dependency

**Why not webhook?** Webhooks require an HTTP server in each consumer. Redis streams are already the established IPC mechanism.

### D8: ML feature service hot-reload on data update

**Choice:** The ML feature service subscribes to `hb.data_catalog.v1` in its main loop. When a relevant update arrives (matching its configured pair and `1m` resolution), it performs a safe window rebuild instead of mutating the deque in place.

**Hot-reload semantics:**
- Loads the parquet tail and combines it with currently retained live bars
- Rebuilds the deque from the sorted unique union, then keeps the newest `ML_ROLLING_WINDOW` bars
- Does not restart the service or flush existing state
- Does not interrupt live bar building from the trade stream
- Logs: "Hot-reloaded N additional bars from parquet for BTC-USDT"

**Why not prepend older bars?** `PairFeatureState` uses `deque(maxlen=ROLLING_WINDOW)`. Prepending into a full deque would evict the newest live bars, which is the opposite of what we want. A rebuild preserves the newest bars and safely fills any missing older context.

### D9: Gap scanning is a separate pass after incremental download

**Choice:** After each incremental download, load the full parquet, run `scan_gaps()`, and if gaps are found, fetch the missing ranges and re-merge.

**Why not detect gaps during download?** The download itself may be clean — gaps could be pre-existing from previous downloads, exchange outages, or DST transitions. A separate full-scan pass catches everything.

### D10: Refresh scope derived from manifest, not hardcoded

**Choice:** The data refresh script reads `config/data_requirements.yml` to compute the union of all consumer needs:
- **Pairs:** union of all consumers' pairs → `["BTC-USDT", "ETH-USDT"]`
- **Canonical exchange datasets:** union of canonical datasets → `["1m", "mark_1m", "index_1m", "funding", "ls_ratio"]`
- **Materialized local datasets:** `["5m", "15m", "1h"]` derived from canonical `1m`
- **Bootstrap / retention:** derived from `bootstrap_from` and `retention_policy`

This means adding a new pair or dataset to any consumer's requirements automatically triggers the refresh pipeline to start fetching or materializing it — no code change needed, just a YAML edit.

### D11: Canonical 1m plus locally materialized higher timeframes

**Choice:** Treat `1m`, `mark_1m`, `index_1m`, `funding`, and `ls_ratio` as canonical exchange-sourced datasets. Materialize `5m`, `15m`, and `1h` locally from canonical `1m` instead of downloading them independently from the exchange.

**Rationale:**
- A single canonical 1m stream eliminates cross-timeframe drift and boundary mismatches
- The ML service already resamples 1m locally, so the codebase already trusts local aggregation
- Backtesting and research can continue reading `5m`/`15m`/`1h` parquet files without changing consumers, but those files become deterministic derivatives of `1m`

**Why not fetch 5m/15m/1h directly?** Independent exchange downloads can disagree with locally reconstructed bars around boundaries, outages, or partial candles. For desk-grade integrity, one canonical base timeframe is safer.

## Risks / Trade-offs

**[Risk] Exchange API rate limits during gap backfill** → Mitigation: `DataDownloader` already uses exponential backoff with 5 retries. Gap backfill uses the same mechanism. If too many gaps exist, the script logs a warning and continues with partial repair rather than blocking.

**[Risk] Parquet file grows large over years** → Mitigation: At 1m resolution, 1 year of BTC-USDT is ~19MB compressed. 5 years would be ~100MB — still fast to read. If needed, partition by year in the future (non-goal for now).

**[Risk] SHA-256 computation on large files slows registration** → Mitigation: The largest file is 39MB. SHA-256 throughput is ~500MB/s on modern hardware. Hash computation takes <100ms. Negligible.

**[Risk] ops-scheduler crash prevents data refresh** → Mitigation: ops-scheduler has `restart: on-failure` and health checks. The refresh interval is 6h, so a single missed cycle means at most 12h of staleness — the ML service can still seed from slightly stale parquet + a larger API bridge.

**[Risk] Clock skew between parquet end_ms and exchange timestamps** → Mitigation: Deduplication by `timestamp_ms` handles overlapping bars. The API bridge fetches from `parquet_end_ms - 5min` to ensure overlap rather than gap.

**[Trade-off] Memory increase in ML service** → 20,160 bars vs 1,440 bars is 14x more data in memory per pair. But the absolute cost is ~1MB per pair, well within the 1GB container limit even with 10 pairs.

**[Trade-off] Startup depends on parquet file existence** → If parquet is missing or corrupt, the service falls back to the existing API-only seed (1,440 bars). This is a graceful degradation, not a failure.

**[Risk] Manifest out of sync with code** → A developer adds a 30-day rolling feature but forgets to update `data_requirements.yml`. Mitigation: each consumer validates at startup that its actual lookback fits within the manifest-declared requirement, logging a warning if manifest is stale. The manifest also includes `derived_from` annotations documenting the source of each number.

**[Risk] Hot-reload race with live bar building** → The ML service appends bars from the trade stream while simultaneously hot-reloading from parquet. Mitigation: hot-reload rebuilds the window from a sorted unique union and keeps the newest `ML_ROLLING_WINDOW` bars, so live bars are preserved.

**[Trade-off] Redis dependency for notifications** → If Redis is down, the data catalog event is lost. Mitigation: the ML service also does a periodic parquet freshness check (every `ML_REFRESH_INTERVAL_S`) as a fallback, so it will eventually pick up new data even without the stream notification.

**[Risk] Missing research-side datasets** → `controllers/ml/research.py` reads `mark_1m`, `index_1m`, `funding`, and `ls_ratio` in addition to standard OHLCV. Mitigation: include these as canonical datasets in the manifest and refresh pipeline from day one.

**[Risk] Cross-timeframe inconsistency** → Downloading `1m`, `5m`, `15m`, and `1h` separately can create inconsistent higher-timeframe bars. Mitigation: make `1m` canonical and materialize higher timeframes locally.
