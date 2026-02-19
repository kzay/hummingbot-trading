# Service Interfaces

## Purpose
Define service responsibilities and integration boundaries.

## Scope
Interfaces among Hummingbot bridge, signal service, risk service, coordination service.

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

## Local Authority (HB)
- Connector readiness gate.
- Intent bounds validation (`target_base_pct` in [0,1]).
- Controller-level rejection reasons written to audit/dead-letter.

## Retry and Idempotency
- `HBIntentConsumer` deduplicates by `event_id`.
- Expired or malformed intents acknowledged and sent to dead-letter.

## Failure Modes
- Redis unavailable -> intent pipeline degrades, local strategy still controlled by internal guards.

## Source of Truth
- `hbot/data/bot1/scripts/v2_with_controllers.py`
- `hbot/services/hb_bridge/*.py`
- `hbot/services/signal_service/main.py`
- `hbot/services/risk_service/main.py`
- `hbot/services/coordination_service/main.py`

## Owner
- Engineering/Platform
- Last-updated: 2026-02-19

