# Day 23 - Wallet/Positions + Blotter v1

## Scope
- Make per-bot wallet/position state visible without opening raw JSON/CSV files.
- Add basic blotter indicators for trade recency and fills volume.

## Implemented
- Extended existing control-plane exporter:
  - `services/control_plane_metrics_exporter.py`
  - added exchange snapshot metrics:
    - `hbot_exchange_snapshot_equity_quote`
    - `hbot_exchange_snapshot_base_pct`
    - `hbot_exchange_snapshot_probe_status`
  - added blotter metrics from `data/*/logs/epp_v24/*/fills.csv`:
    - `hbot_bot_blotter_fills_total`
    - `hbot_bot_blotter_last_fill_timestamp_seconds`
    - `hbot_bot_blotter_last_fill_age_seconds`
  - fallback behavior:
    - emits `variant=no_fills` zeroed blotter metrics when no fills file exists yet, so dashboard remains explicit (not blank).
- Compose exporter runtime updated with explicit data root:
  - `compose/docker-compose.yml`
  - `HB_DATA_ROOT=/workspace/hbot/data`
- Added Grafana dashboard:
  - `monitoring/grafana/dashboards/wallet_blotter_v1.json`
  - title: `Trading Desk Wallet and Blotter`

## Validation
- Python compile passes for updated exporter.
- Exporter render smoke test emits wallet + blotter metrics.
- Compose config validation passes with updated exporter environment.

## Result
- Operators can answer:
  - what each bot holds (`equity_quote`, `base_pct`)
  - whether account probe state is present
  - whether a bot traded recently (`last_fill_age_seconds`, `fills_total`)
