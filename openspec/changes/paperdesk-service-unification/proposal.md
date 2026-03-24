## Why

The workspace currently has two independent paper-exchange implementations:

- `hbot/controllers/paper_engine_v2/` (`PaperDesk`) is the richer and better-structured engine used by backtesting and in-process paper trading.
- `hbot/services/paper_exchange_service/main.py` is a separate service implementation with its own matching, accounting, funding, and persistence logic.

These two implementations simulate the same exchange with different code paths. That creates permanent divergence risk, which already materialized in the ONEWAY accounting bug. If paper bots, replay, dashboard, and ops readers are meant to trust one source of truth, they must ultimately run on one simulation engine.

The best architecture is not "service only" and not "keep both engines". It is:

- one engine (`PaperDesk`)
- two deployment modes
  - embedded mode for backtesting/replay
  - service mode for paper bots

This preserves fast synchronous backtests while removing duplicated exchange logic from the runtime service.

## What Changes

- Replace the legacy Paper Exchange Service monolith with a thin service wrapper around `PaperDesk`.
- Add a service router that keeps one `PaperDesk` instance per `instance_name` so bot balances, positions, and risk state stay isolated.
- Add a compatibility projection layer that writes the current paper-exchange snapshots and journals expected by downstream consumers, including open orders.
- Keep Redis command, event, heartbeat, and audit contracts unchanged.
- Keep `BOT_MODE=paper|live` and existing connector naming unchanged; bots should not need `paper_bitget` or similar aliases.
- Keep backtesting and replay embedded on the `PaperDesk` library; they do not go through Redis.
- Simplify `hb_bridge.py` so the active paper path routes to the service instead of building an in-process desk for paper bots.

## Capabilities

### New Capabilities

- `paperdesk-service-mode`: Contract-compatible service mode powered by `PaperDesk`
- `paperdesk-tenant-isolation`: One paper desk per bot instance in service mode
- `paperdesk-compat-projection`: Snapshot/journal projection preserving existing consumers
- `paperdesk-instrument-registry`: Deterministic instrument registration before accepting orders

### Modified Capabilities

- `paper-bot-routing`: Paper bots route to the service-backed `PaperDesk` instead of the legacy monolith

## Impact

- `hbot/services/paper_exchange_service/main.py` will be replaced or retired as legacy
- `hbot/controllers/paper_engine_v2/` becomes the only exchange simulation engine
- `hbot/controllers/paper_engine_v2/hb_bridge.py` will lose in-process paper-bot desk ownership in active mode
- `hbot/services/realtime_ui_api/fallback_readers.py` and other snapshot consumers keep their current contract
- `hbot/controllers/backtesting/` remains embedded on `PaperDesk`
- `paper-exchange-accounting-hardening` remains complementary and should stay in force for regression coverage
