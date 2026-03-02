# Service Interfaces

## Purpose
Define service responsibilities and integration boundaries.

## Scope
Interfaces among Hummingbot bridge, signal service, risk service, coordination service, and paper exchange service.

## Service Responsibilities
- Hummingbot bridge (`v2_with_controllers.py`)
  - publish market snapshots
  - consume intents
  - apply local authority checks
- Signal service
  - consume `market_data`
  - produce `signal` or `ml_signal`
- Risk service
  - consume `signal`/`ml_signal`
  - produce `risk_decision`
- Coordination service
  - consume `risk_decision`
  - produce `execution_intent`
- Paper exchange service (`services/paper_exchange_service/main.py`)
  - consume `market_snapshot` (source-of-truth market feed from real connector path)
  - consume `paper_exchange_command`
  - produce `paper_exchange_event`
  - produce `paper_exchange_heartbeat`

## Paper Exchange Streams
- `hb.paper_exchange.command.v1`
  - commands addressed to paper exchange (`submit_order`, `cancel_order`, `cancel_all`, `sync_state`)
- `hb.paper_exchange.event.v1`
  - command lifecycle outcomes (`processed` / `rejected`) with reason codes
- `hb.paper_exchange.heartbeat.v1`
  - service health/freshness heartbeat for SLO and promotion gating

## Paper Exchange Rollout Modes
- `PAPER_EXCHANGE_MODE` (or per-instance `PAPER_EXCHANGE_MODE_<BOT>`) controls bridge routing:
  - `disabled`: legacy in-process paper path only
  - `shadow`: dual-write commands to service while legacy path remains source-of-truth
  - `active`: commands routed to paper-exchange service with startup sync handshake gate
- Compose profile `paper-exchange` starts `paper-exchange-service` for canary/active rollout windows.

## Local Authority (HB)
- Connector readiness gate.
- Intent bounds validation (`target_base_pct` in [0,1]).
- Controller-level rejection reasons written to audit/dead-letter.

## Retry and Idempotency
- `HBIntentConsumer` deduplicates by `event_id`.
- Expired or malformed intents acknowledged and sent to dead-letter.

## Failure Modes
- Redis unavailable -> intent pipeline degrades, local strategy still controlled by internal guards.

## Event Payload Semantics
- `bot_fill.realized_pnl_quote`
  - **Paper (`accounting_source=paper_desk_v2`)**: emitted as the controller's per-fill realized PnL delta (`_realized_pnl_today` after fill minus before fill).
  - **Live (`accounting_source=live_connector`)**: emitted from controller fill accounting at fill time.
  - **Expected zero** only when the fill does not close any existing exposure (pure inventory build/open leg).
  - **Expected non-zero** when the fill closes part/all of an existing position.

## Source of Truth
- `hbot/scripts/shared/v2_with_controllers.py` — strategy entry point
- `hbot/controllers/paper_engine_v2/hb_bridge.py` — bridge, signal consumer, kill-switch publisher
- `hbot/services/hb_bridge/*.py` — Redis client, intent consumer, publisher
- `hbot/services/paper_exchange_service/main.py` — paper exchange service process
- `hbot/services/signal_service/main.py`
- `hbot/services/risk_service/main.py`
- `hbot/services/coordination_service/main.py`

## Owner
- Engineering/Platform
- Last-updated: 2026-02-27

