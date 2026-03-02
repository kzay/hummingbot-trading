## Trading Desk Observability Contract (HBot)

This repo’s Grafana dashboards are **contract-driven**: every number must map to a concrete in-repo source (CSV/JSON/log) exported via **Prometheus** and/or **Loki**. If a requested KPI cannot be derived from existing artifacts, it must be explicitly marked “not available” until instrumented.

### Canonical entities (dashboard + metric model)

- **bot_id**: Prometheus label `bot` (e.g. `bot1`)
- **exchange**: label `exchange` (e.g. `bitget_paper_trade`, `bitget_perpetual`)
- **market / symbol**: label `pair` (e.g. `BTC-USDT`)
- **strategy**: label `variant` (strategy role/variant; e.g. `a`, `paper_validation`)
- **environment**: label `environment` (Prometheus `external_labels`; default in this repo: `production`)
- **cluster**: label `cluster` (Prometheus `external_labels`; default in this repo: `hbot-prod`)
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
- `cluster`, `environment` (from `hbot/monitoring/prometheus/prometheus.yml` `external_labels`)

### Logs contract (Loki via promtail)

Promtail scrapes on-disk artifacts from `hbot/data/**` and attaches stable labels:
- **Bot runtime logs**: `data/<bot>/logs/*.log` → `{job="bot_logs", bot="<bot>", filename="..."}`
- **EPP CSV artifacts**: `data/<bot>/logs/epp_v24/*/*.csv` → `{job="epp_csv", bot="<bot>", filename="..."}`

### Time, freshness, retention

- **Timezone**: dashboards are **UTC** (required for trading).
- **Update cadence**:
  - Prometheus scrape: **15s** (bot/control-plane exporters), **10s** (node-exporter/cAdvisor).
  - Most trading KPIs originate from `minute.csv` and update **~60s**. Scraping faster reduces UI latency but does not create new information.
- **Retention (defaults)**:
  - Prometheus: **30d** (`PROMETHEUS_RETENTION=30d` in `hbot/compose/docker-compose.yml`)
  - Loki: **7d** (`retention_period: 168h` in `hbot/monitoring/loki/loki-config.yml`)

### Dashboard variables (canonical, consistent)

Grafana variables must align to canonical entities and existing labels:
- `bot` → label `bot`
- `exchange` → label `exchange`
- `symbol` → label `pair`
- `strategy` → label `variant`
- `environment` → label `environment`
- `cluster` → label `cluster`
- `venue` → label `mode`
- `regime` → label `regime`

Dashboard-only variables (no Prometheus label):
- `timeframe`: a controlled interval list used for deltas/rollups (e.g. `5m`, `15m`, `1h`)
- `account`: **UI concept only** today (maps to `bot` until an `account` label exists)

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

