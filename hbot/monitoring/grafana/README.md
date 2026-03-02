## HBot Grafana dashboards (Trading Desk)

This repo provisions Grafana dashboards from disk (no manual import needed) and uses **Prometheus** + **Loki** only (both OSS, already in `hbot/compose/docker-compose.yml`).

### Dashboards

- **Trading Desk**: `hbot/monitoring/grafana/dashboards/trading_overview.json` (UID: `hbot-trading-overview`)
- **Bot Deep Dive** (drilldown): `hbot/monitoring/grafana/dashboards/bot_deep_dive.json` (UID: `hbot-bot-deep-dive`)
- **Ops & Infrastructure**: `hbot/monitoring/grafana/dashboards/control_plane_health.json` (UID: `hbot-cp-health`)

### Data sources (provisioned)

Defined in `hbot/monitoring/grafana/provisioning/datasources/datasource.yml`:
- **Prometheus** (uid `prometheus`, default)
- **Loki** (uid `loki`)

### Variables (Trading Desk + Deep Dive)

All time is **UTC**.

- **cluster**: Prometheus `external_labels.cluster`
- **environment**: Prometheus `external_labels.environment`
- **account**: *UI concept only* today; maps to `bot` until an `account` label exists
- **bot**: Prometheus label `bot`
- **exchange**: label `exchange`
- **symbol**: label `pair`
- **strategy**: label `variant`
- **venue**: label `mode` (`paper` / `live`)
- **regime**: label `regime`
- **timeframe**: a dashboard interval (`5m`, `15m`, `1h`) used for deltas/rollups

### Panel guide (Trading Desk)

**Desk Health**
- Quick decision row: bots running, desk equity, today’s MTM PnL, realized PnL, max drawdown, and a desk **uptime proxy**.
- Execution + ops pulse: gross/net exposure, fills and fees over `$timeframe`, slippage vs mid (bps), and ERROR logs/min (Loki).

**Risk**
- Integrity + liquidation proximity: position drift %, inventory skew %, worst margin ratio, funding pressure, and exposure trend.

**Execution Quality**
- Maker share over `$timeframe`, cancel rate, adverse drift 30s (bps), stale order book %, tick duration, WS reconnect activity.

**Strategy KPIs**
- Per-bot table (click bot name → Deep Dive).

**Ops**
- Active alerts + recent WARN/ERROR logs.

### Post-import / post-deploy verification checklist

After bringing the stack up (or after updating dashboards/exporters):

- **Grafana provisioning**
  - Confirm the dashboards appear under the `Hummingbot` folder.
  - Confirm datasources exist with UIDs `prometheus` and `loki`.

- **Prometheus targets**
  - In Prometheus UI → *Status → Targets*: `bot-metrics` and `control-plane-metrics` are **UP**.
  - New bot KPIs should exist (examples):
    - `hbot_bot_fill_slippage_bps_sum`
    - `hbot_bot_adverse_drift_30s_bps_sum`

- **Recording rules**
  - `hbot/compose/docker-compose.yml` mounts `recording_rules.yml` into Prometheus.
  - In Prometheus UI → *Status → Rules*: verify rules like `hbot_bot_running_fresh` and `hbot_bot_inventory_skew_abs` are present.
  - If rules are missing, restart Prometheus or hit `POST /-/reload` (Prometheus supports reload in this compose setup).

- **Loki logs**
  - In Grafana Explore (Loki), verify `{job="bot_logs"}` returns log lines.

- **Sanity checks**
  - **Uptime (Healthy)** is near 100% when bots are running and writing `minute.csv` every ~60s.
  - **Slippage vs Mid** moves when fills occur (derived from `fills.csv` `mid_ref` + `price`).
  - **Errors/min** spikes align with the “Recent Bot Logs” panel.

