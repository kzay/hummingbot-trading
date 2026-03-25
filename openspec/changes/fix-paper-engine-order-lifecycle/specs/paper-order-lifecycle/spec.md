## ADDED Requirements

### Requirement: Paper bridge fires order acceptance events
When the paper engine accepts an order (`OrderAccepted` from `simulation.types`), the bridge SHALL translate it into a `BuyOrderCreatedEvent` or `SellOrderCreatedEvent` (depending on `event.side`) and dispatch it to the Hummingbot framework via the strategy's event trigger.

#### Scenario: Buy limit order accepted in paper engine
- **WHEN** a `PositionExecutor` places a buy limit order and the paper engine returns `OrderAccepted` with `order_id=pe-abc123` and `side="buy"`
- **THEN** the bridge SHALL fire a `BuyOrderCreatedEvent` with `order_id=pe-abc123`, `trading_pair` from the event, `order_type=LIMIT`, and `amount` matching `event.quantity`

#### Scenario: Sell limit order accepted in paper engine
- **WHEN** a `PositionExecutor` places a sell limit order and the paper engine returns `OrderAccepted` with `order_id=pe-xyz789` and `side="sell"`
- **THEN** the bridge SHALL fire a `SellOrderCreatedEvent` with `order_id=pe-xyz789`, `trading_pair`, `order_type=LIMIT`, and `amount` matching `event.quantity`

#### Scenario: Market order accepted in paper engine
- **WHEN** a `PositionExecutor` places a market order and the paper engine returns `OrderAccepted`
- **THEN** the bridge SHALL fire the corresponding `BuyOrderCreatedEvent` or `SellOrderCreatedEvent` before any subsequent fill event

#### Scenario: Order rejected — no acceptance event
- **WHEN** the paper engine returns `OrderRejected`
- **THEN** the bridge SHALL NOT fire an acceptance event; the existing `OrderRejected` handler remains the sole response

### Requirement: Deduplication of `OrderAccepted` events
When insert latency is configured (`paper_insert_latency_ms > 0`), the matching engine emits `OrderAccepted` TWICE for the same `order_id`: once at submission (synchronous return from `submit_order`) and again when the latency queue drains in `tick()`. The bridge SHALL fire the acceptance HB event ONLY ONCE per `order_id`.

#### Scenario: Zero-latency — single acceptance event
- **WHEN** `paper_insert_latency_ms=0` and a limit order is submitted
- **THEN** `submit_order` returns `OrderAccepted` once, the bridge fires `BuyOrderCreatedEvent`/`SellOrderCreatedEvent` once

#### Scenario: Non-zero latency — deduplication
- **WHEN** `paper_insert_latency_ms=20` and a limit order is submitted
- **THEN** `submit_order` returns `OrderAccepted` at submission time; `desk.tick()` returns another `OrderAccepted` for the same `order_id` when latency elapses
- **AND** the bridge SHALL fire the HB event on the FIRST occurrence and silently skip the second

#### Scenario: Dedup tracking scope
- **WHEN** `OrderAccepted` for `pe-abc123` fires, then `OrderCanceled` for `pe-abc123` fires, then a NEW order with `pe-abc123` is submitted (theoretically reusing ID)
- **THEN** the dedup set SHALL be cleared for that `order_id` on cancel/fill/reject so re-use is not blocked

### Requirement: Shadow mode and active mode both fire acceptance events
In shadow mode, `_patched_order` calls `desk.submit_order()` then `_fire_hb_events`. In active mode, `_patched_order` does NOT call `desk.submit_order` — acceptance arrives asynchronously via `drive_desk_tick` → `_consume_paper_exchange_events`. The `_fire_accept_event` handler SHALL work correctly in both paths since it is invoked from `_fire_hb_events` which is called by both.

#### Scenario: Shadow mode acceptance
- **WHEN** bridge mode is `shadow` and `_patched_order` calls `desk.submit_order()` returning `OrderAccepted`
- **THEN** `_fire_hb_events` is called with the `OrderAccepted` event and the bridge fires the HB acceptance event

#### Scenario: Active mode deferred acceptance
- **WHEN** bridge mode is `active` and `_patched_order` upserts as `pending_create`
- **THEN** `drive_desk_tick` later consumes the paper exchange response including acceptance, calls `_fire_hb_events`, and the bridge fires the HB acceptance event

### Requirement: Runtime order tracking on acceptance
When an `OrderAccepted` event is translated, the bridge SHALL upsert the order into the runtime order store (`_paper_exchange_runtime_orders`) with the order's `order_id`, side, trading pair, amount, price, and status `working`.

#### Scenario: Order tracked after acceptance
- **WHEN** a buy limit order is accepted with `order_id=pe-abc123`
- **THEN** `strategy._paper_exchange_runtime_orders[connector_name][pe-abc123]` SHALL exist with `trade_type=BUY`, `current_state=working`, `amount`, and `price` matching the event

#### Scenario: Fill event finds tracked order
- **WHEN** a previously accepted order `pe-abc123` is later filled
- **THEN** the fill handler SHALL find the runtime order in `_paper_exchange_runtime_orders` and correctly resolve `trade_type` from it

#### Scenario: Shadow mode runtime order upsert
- **WHEN** shadow mode fires `OrderAccepted` from `_patched_order`
- **THEN** the runtime order upsert SHALL use the same `_upsert_runtime_order` helper (or equivalent) to ensure field consistency with active mode

### Requirement: Desk tick propagates acceptance events
When `drive_desk_tick` processes engine events after a `desk.tick()`, any `OrderAccepted` events returned from the engine's deferred processing (latency queue drain) SHALL be translated and dispatched through the same `_fire_hb_events` handler. The deduplication requirement (above) ensures these don't double-fire.

#### Scenario: Deferred acceptance after latency
- **WHEN** paper engine config has `paper_insert_latency_ms: 20` and an order enters the `_inflight` queue
- **THEN** on the next `desk.tick()` that drains the latency queue, the resulting `OrderAccepted` SHALL pass through `_fire_hb_events` but be silently skipped if the first acceptance for that `order_id` was already dispatched

### Requirement: Event ordering guarantee
The bridge SHALL fire the acceptance event (`BuyOrderCreatedEvent`/`SellOrderCreatedEvent`) BEFORE any fill event for the same `order_id`.

#### Scenario: Immediate market fill
- **WHEN** a market order is accepted and filled in the same engine tick
- **THEN** `BuyOrderCreatedEvent` SHALL be dispatched before `OrderFilledEvent` for the same `order_id`

#### Scenario: Limit order fill after acceptance
- **WHEN** a limit order is accepted, then filled on a subsequent tick
- **THEN** the acceptance event SHALL have been dispatched on the submission tick, and the fill event on the later tick

### Requirement: Correct imports and type usage
The `_fire_accept_event` handler SHALL import `OrderAccepted` from `simulation.types` (NOT from `platform_lib.contracts.event_schemas` which does not define it). `BuyOrderCreatedEvent` and `SellOrderCreatedEvent` SHALL be imported from the Hummingbot event type module.
