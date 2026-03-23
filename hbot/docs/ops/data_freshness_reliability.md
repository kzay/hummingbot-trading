# Data freshness and reliability (operator checklist)

Goals: **strong** (correct merges), **reliable** (no silent gaps), **fast** (low latency to UI).

## Stack dependencies

1. **Redis** — streams for realtime API consumer; password must match `REDIS_URL` / `REDIS_PASSWORD` (see compose `x-kzay-env`).
2. **market_data_service** — enable when you need canonical L1/L2/trade streams (`MARKET_DATA_SERVICE_ENABLED=true`).
3. **event_store** + **ops_db_writer** — durable mirror and SQL read path for history / dashboard DB mode.
4. **Mosquitto** — Hummingbot `mqtt_bridge` host `mosquitto` on the `trading` network (compose service).

## Realtime dashboard (`realtime_ui_api` + `realtime_ui_v2`)

| Variable | Role |
|----------|------|
| `REALTIME_UI_API_POLL_MS` | How often the API merges stream + REST (default `200`). |
| `REALTIME_UI_API_STREAM_STALE_MS` | Age at which stream is treated as stale vs heartbeat. |
| `REALTIME_UI_API_DB_ENABLED` | Postgres-backed fills/activity when `true`. |
| `REALTIME_UI_API_USE_CSV` | Default `false`. The dashboard uses **stream + DB + JSON desk snapshots** only; set `true` only for local debug when you intentionally read `minute.csv` / `fills.csv` via the API. |
| `REALTIME_UI_API_CSV_FAILOVER_ONLY` | When `USE_CSV` is `true`, if this is `true` then CSV is used only when the DB read path is unavailable; if `false`, CSV can supplement even when the DB is up. |
| `REALTIME_UI_API_SSE_ENABLED` | Server-Sent Events to the browser; reduces gap vs poll-only. |

The UI client **merges REST by segment**: fill-derived **activity** updates when fill timestamps advance even if a market snapshot in the same payload is older than the WS quote (avoids frozen 15m/1h cards). **Account** summary still requires consistent market/position/fill guards.

## Bot artifacts

- **`minute.csv` / `fills.csv`** — on-disk backup / debug; Prometheus and the operator UI should not depend on them as the primary path (enable `REALTIME_UI_API_USE_CSV` only when debugging).
- **Heartbeat JSON** — watchdog / health; keep fresh for container healthchecks.

## Promotion / quality gates

- `reports/verification/realtime_l2_data_quality_latest.json` — L2 stream quality.
- `reports/ops_db_writer/latest.json` — DB mirror coverage.

Refresh these on a schedule when changing the data path.
