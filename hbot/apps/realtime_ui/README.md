# Realtime UI (TradingView-like)

Static web UI for operator/trader execution view:

- Price candles (lightweight-charts)
- Position and PnL summary
- Open orders overlay/table
- Recent fills feed
- L2 depth ladder
- Live updates via SSE from `realtime-ui-api`

## Local run

```bash
cd hbot/apps/realtime_ui
python -m http.server 8088
```

Then open <http://localhost:8088> and point API URL to `http://localhost:9910`.

## Make a new bot visible

To make a new bot instance appear in the supervision UI before it emits live
stream traffic or desk snapshots, create its supervision manifest:

```bash
python hbot/scripts/ops/create_supervision_instance_manifest.py --instance bot8 --controller-id epp_v2_4_bot8 --trading-pair BTC-USDT --label "Bot 8"
```

Optional:

- add `--create-marker` to also write `hbot/data/<bot>/.supervision_enabled`
- use `--root hbot` when running from the repository root
