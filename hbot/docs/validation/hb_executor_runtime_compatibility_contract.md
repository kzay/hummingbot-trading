# HB Executor Runtime Compatibility Contract v1

## Purpose

Define the compatibility contract between `paper_exchange_event` processing and
Hummingbot executor/runtime expectations while the bridge layer remains active.

## Scope

- Bridge: `controllers/paper_engine_v2/hb_bridge.py`
- Event source: `hb.paper_exchange.event.v1`
- Runtime fallback: `ExecutorBase.get_in_flight_order` compatibility patch

## Order Lifecycle Mapping Contract

`paper_exchange_event` records in active mode MUST map to HB-facing semantics as follows:

- `submit_order` + `status=rejected` -> `OrderRejected`
- `submit_order` + `status=processed` + `metadata.order_state=filled|partially_filled` -> `OrderFilled`
- `submit_order` + `status=processed` + `metadata.order_state=expired` -> `OrderRejected`
- `cancel_order` + `status=processed` -> `OrderCanceled`
- `order_fill|fill|fill_order` + `status=processed` -> `OrderFilled`

## Runtime In-Flight Contract

For executor lookup compatibility, `get_in_flight_order(connector, order_id)` MUST:

1. Resolve runtime-order entries from bridge runtime store first.
2. Support canonical connector fallback (`*_paper_trade` -> canonical connector key).
3. Fall back to connector tracker lookup when runtime store has no match.
4. Return `None` (not exception) when lookup fails.

## Runtime State Parity

Runtime order state transitions from service events MUST preserve executor visibility:

- `pending_create -> open|partial|filled|failed|expired`
- `open|partial -> pending_cancel|canceled|filled|failed`
- Terminal states (`filled|canceled|failed|expired`) remain queryable until TTL prune.

## Verification Evidence

- Functional scenario: `hb_executor_runtime_compatibility` in
  `scripts/release/run_paper_exchange_golden_path.py`
- Unit/integration coverage:
  - `TestPaperExchangeActiveAdapter` lifecycle mapping tests
  - `TestExecutorInflightCompatibility` fallback tests
- Threshold evidence artifact:
  - `reports/verification/paper_exchange_hb_compatibility_latest.json`
  - Metrics: `p0_11_*`
