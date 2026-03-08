# Service Interfaces

## Purpose
Define service responsibilities and integration boundaries.

## Scope
Interfaces among Hummingbot bridge, signal service, risk service, coordination service,
paper exchange service, and promotion-gate consumers.

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

## Canonical Stream Contracts (Ownership + Failure Policy)
| Stream | Primary Producer | Primary Consumers | Ownership | Failure Policy |
|---|---|---|---|---|
| `hb.market_data.v1` | HB bridge/controller runtime | `signal-service`, `paper-exchange-service`, event store | Data plane | stale market data causes deterministic command rejection in paper-exchange service; no silent mid-only fallback in active mode |
| `hb.signal.v1` | `signal-service` | `risk-service`, bridge signal consumer | Strategy plane | unknown/late signal is skipped/rejected with auditable reason; tick loop must continue |
| `hb.ml_signal.v1` | optional ML signal producers | `risk-service` | Strategy plane | stale ML signal treated as non-authoritative input |
| `hb.risk_decision.v1` | `risk-service` | `coordination-service` | Risk plane | explicit reason codes required; denied decisions must be traceable |
| `hb.execution_intent.v1` | `coordination-service` | HB intent consumer, `kill-switch-service` | Control plane | at-least-once delivery with intent expiry and dead-letter path |
| `hb.paper_exchange.command.v1` | HB active adapter / bridge | `paper-exchange-service` | Execution plane | idempotency + pending reclaim mandatory for correctness under redelivery |
| `hb.paper_exchange.event.v1` | `paper-exchange-service` | HB adapter, event store, parity/reporting scripts | Execution plane | one deterministic terminal outcome per command id; replay must not duplicate side effects |
| `hb.paper_exchange.heartbeat.v1` | `paper-exchange-service` | reliability SLO, preflight, strict promotion gates | Execution/ops plane | stale/missing heartbeat is critical when paper-exchange checks are enabled |
| `hb.audit.v1` | bridge/services/release checks | event store, ops tooling | Governance plane | privileged action metadata is required for operator attribution |
| `hb.dead_letter.v1` | bridge/services | ops/reliability checks | Reliability plane | dead-letter growth and critical reasons are gate-visible diagnostics |

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

## Startup Sync Contract (Active Mode)
- Controller/bridge must complete startup sync handshake before quoting.
- Active routing cannot emit live paper-exchange commands before `sync_state` acceptance.
- Sync timeout/failure transitions to explicit safety state (`HARD_STOP`/kill-switch intent),
  never silent continuation.

## Active-Mode Failure Policy Matrix
| Failure Class | Trigger Examples | Controller Action | Standardized Reason Pattern |
|---|---|---|---|
| `service_down` | `redis_unavailable`, `command_publish_failed`, command publish exceptions | `soft_pause` (external intent) | `paper_exchange_soft_pause:service_down:<reason>` |
| `stale_feed` | `stale_market_snapshot`, `no_market_snapshot` | `soft_pause` (external intent) | `paper_exchange_soft_pause:stale_feed:<reason>` |
| `command_backlog` | `expired_command` | `soft_pause` (external intent) | `paper_exchange_soft_pause:command_backlog:<reason>` |
| `recovery_loop` | repeated failures on same `(instance, connector, pair)` | `hard_stop` (`force_hard_stop`) | `paper_exchange_recovery_loop:<class>:<reason>` |

- Failure streak tracking is namespace-scoped per `(instance_name, connector_name, trading_pair)`.
- Successful active-mode processed outcomes reset the streak and issue `resume` intent.
- Silent fallback to in-process/live execution is forbidden in active mode.

## Local Authority (HB)
- Connector readiness gate.
- Intent bounds validation (`target_base_pct` in [0,1]).
- Controller-level rejection reasons written to audit/dead-letter.

## Retry and Idempotency
- `HBIntentConsumer` deduplicates by `event_id`.
- Expired or malformed intents acknowledged and sent to dead-letter.
- Paper-exchange command processing deduplicates by `command_event_id` and reclaims stale
  pending entries via consumer-group recovery flow.

## Failure Modes
- Redis unavailable -> intent pipeline degrades, local strategy still controlled by internal guards.
- Paper-exchange heartbeat stale/missing -> strict preflight/gate fail (when enabled).
- Threshold inputs unresolved/stale -> strict cycle fail with explicit diagnostics in
  `reports/promotion_gates/latest.json` and `reports/promotion_gates/strict_cycle_latest.json`.

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
- Last-updated: 2026-03-04

