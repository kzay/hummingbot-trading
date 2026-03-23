## Kzay Capital Trading Desk Observability Contract

This repo’s metrics are **contract-driven**: every number must map to a concrete in-repo source (CSV/JSON/log) exported via **Prometheus**. If a requested KPI cannot be derived from existing artifacts, it must be explicitly marked “not available” until instrumented.

### Canonical entities (dashboard + metric model)

- **bot_id**: Prometheus label `bot` (e.g. `bot1`, `bot2`, `bot3`, `bot4`, `bot5`, `bot6`, `bot7`)
- **exchange**: label `exchange` (e.g. `bitget_paper_trade`, `bitget_perpetual`)
- **market / symbol**: label `pair` (e.g. `BTC-USDT`)
- **strategy**: label `variant` (strategy role/variant; e.g. `a`, `paper_validation`)
- **environment**: label `environment` (Prometheus `external_labels`; default in this repo: `production`)
- **cluster**: label `cluster` (Prometheus `external_labels`; default in this repo: `kzay-capital-prod`)
- **venue_type**:
  - **execution mode**: label `mode` (`paper` / `live`)
  - **instrument type (spot vs perp)**: derived (until first-class) from `exchange` naming (e.g. `.*_perpetual.*` ⇒ futures/perps)
- **account**: **not first-class today**
  - **current operational boundary**: use `bot` as “account” (one bot ↔ one credential set).
  - **future recommendation**: introduce label `account` from `config/exchange_account_map.json` / exchange snapshot payloads.

### Metric namespaces + label rules

- **Bot runtime + strategy KPIs**: `hbot_bot_*` (exported by `hbot/services/bot_metrics_exporter.py`)
- **Control-plane / gates / exchange snapshots**: `hbot_control_plane_*`, `hbot_exchange_snapshot_*`, `hbot_bot_blotter_*`, `hbot_coordination_*` (exported by `hbot/services/control_plane_metrics_exporter.py`)
- **Infra**: standard `node_*` and `container_*` (node-exporter + cAdvisor)

All `hbot_bot_*` series emitted by the bot exporter include these labels:
- `bot`, `variant`, `mode`, `accounting`, `exchange`, `pair`, `regime`

Additional metric-specific labels:
- `hbot_bot_state`: adds label `state`
- `hbot_bot_fee_source_info`: adds label `source`
- `hbot_bot_risk_reasons_info`: adds label `reasons`

All Prometheus series also include:
- `cluster`, `environment` (from `hbot/infra/monitoring/prometheus/prometheus.yml` `external_labels`)

### Time, freshness, retention

- **Timezone**: all timestamps are **UTC** (required for trading).
- **Update cadence**:
  - Prometheus scrape: **15s** (bot/control-plane exporters), **10s** (node-exporter/cAdvisor).
  - Most trading KPIs originate from `minute.csv` and update **~60s**. Scraping faster reduces UI latency but does not create new information.
- **Retention (defaults)**:
  - Prometheus: **30d** (`PROMETHEUS_RETENTION=30d` in `hbot/infra/compose/docker-compose.yml`)

### “No mystery numbers” source-of-truth mapping

`hbot_bot_*` metrics derive from the bot’s local artifacts:
- `data/<bot>/logs/epp_v24/*/minute.csv` (latest row)
- `data/<bot>/logs/epp_v24/*/fills.csv`
- `data/<bot>/logs/epp_v24/*/daily_state*.json`
- `data/<bot>/logs/*.log` (tail-scan for ERROR density)

`hbot_control_plane_*` / `hbot_exchange_snapshot_*` derive from:
- `hbot/reports/**/latest.json` and related gate artifacts
- `hbot/reports/exchange_snapshots/latest.json`
- `data/<bot>/.../fills.csv` blotter stats (row count + last fill time)

### Realtime UI + L2 contract (stream-first read path)

New operator execution UI reads from:

- `hb.market_data.v1` (L1 snapshots, backward compatible)
- `hb.market_depth.v1` (L2 depth snapshots)
- `hb.bot_telemetry.v1` (fills/telemetry feed)
- `hb.paper_exchange.event.v1` (order/event lifecycle feed)

Operational evidence artifacts:

- `reports/verification/realtime_l2_data_quality_latest.json`
- `reports/ops_db_writer/latest.json` (`counts.market_depth.*`)
- `reports/event_store/integrity_*.json` (`events_by_stream`)

Strict-cycle quality dimensions:

- ingest freshness (event-store integrity + depth stream age)
- sequence integrity (gaps / out-of-order / duplicates)
- sampling coverage and raw-vs-sampled parity
- storage budget controls (depth stream share + payload-size budget)

