# Implementation Tasks

## 1. Paper Bridge — Order Acceptance Events (shared: `hbot/simulation/bridge/`)

### 1.1 Add `_fire_accept_event` handler in `hb_event_fire.py`
- Import `OrderAccepted` from `simulation.types` (NOT `event_schemas.py` — it doesn't define `OrderAccepted`)
- Import `BuyOrderCreatedEvent`, `SellOrderCreatedEvent` from Hummingbot event types
- Create `_fire_accept_event(strategy, connector_name, event: OrderAccepted, bridge_state)`:
  - Resolve `trade_type` from `event.side` ("buy" → `TradeType.BUY`, "sell" → `TradeType.SELL`)
  - Build the appropriate HB event (`BuyOrderCreatedEvent` / `SellOrderCreatedEvent`) with `order_id`, `trading_pair` (from `event` context), `order_type`, `amount=event.quantity`, `price=event.price`
  - Dispatch via `strategy.trigger_event(...)` matching the pattern in `_fire_fill_event`
  - Resolve controller via same `_resolve_controller_for_event` pattern used in fill/cancel paths for `instance_name` routing
- Add `OrderAccepted` branch to `_fire_hb_events`:
  ```python
  elif isinstance(event, OrderAccepted):
      _fire_accept_event(strategy, connector_name, event, bridge_state)
  ```

### 1.2 Implement `OrderAccepted` deduplication
- Add a dedup set for accepted `order_id`s, stored on `bridge_state` (e.g., `bridge_state._accepted_order_ids: set[str]`)
- In `_fire_accept_event`, check if `event.order_id` is already in the set; if so, return early (no-op)
- On first acceptance, add `order_id` to the set, then proceed with event dispatch
- Clear `order_id` from the set when `OrderCanceled`, `OrderFilled`, or `OrderRejected` is processed for the same `order_id` (add cleanup lines to `_fire_cancel_event`, `_fire_fill_event`, `_fire_reject_event`)
- This handles the double-`OrderAccepted` from insert latency simulation

### 1.3 Upsert runtime order on acceptance
- In `_fire_accept_event`, after dispatching the HB event, upsert the order into `strategy._paper_exchange_runtime_orders` using `_upsert_runtime_order` (or equivalent helper) with:
  - `order_id = event.order_id`
  - `trade_type = "BUY"` or `"SELL"` from `event.side`
  - `current_state = "working"`
  - `amount = event.quantity`, `price = event.price`
  - `trading_pair` from event context
- This ensures the fill handler can find the runtime order for side resolution

### 1.4 Extend `_dispatch_to_subscribers` for `OrderAccepted` (optional)
- OPTIONAL: Add `on_accept` to the `EventSubscriber` protocol
- Add `isinstance(event, OrderAccepted)` branch to `_dispatch_to_subscribers`
- Subscribers that don't implement `on_accept` get a no-op default
- This is a nice-to-have; the primary fix path is the HB event fire (1.1)

### 1.5 Verify `_patched_order` (shadow mode) and `drive_desk_tick` both call `_fire_hb_events`
- **Shadow mode**: `_patched_order` already calls `_fire_hb_events(self, route_connector_name, event, _bridge_state)` with the `submit_order` result. Verify `OrderAccepted` flows through. No code change expected — just verification.
- **Active mode**: `drive_desk_tick` calls `_fire_hb_events(strategy, conn_name, event, _bridge_state)` for each desk tick event. Verify `OrderAccepted` events from deferred latency queue drain flow through. No code change expected — just verification.
- **Ensure event ordering**: In `_fire_hb_events`, acceptance branch MUST be before fill branch (or simply use `elif` chain which naturally provides first-match ordering).

### 1.6 Verify `OrderAccepted` fields match handler expectations
- `OrderAccepted` dataclass fields: `order_id`, `side`, `order_type`, `price`, `quantity`, `source_bot`, `instance_name`, `position_action`
- The handler needs `trading_pair` — this is NOT a field on `OrderAccepted`. Resolve from:
  - The `connector_name` parameter (which maps to an instrument), OR
  - Look up via `bridge_state` or the desk's instrument registry
  - Document how `trading_pair` is obtained; this must be tested

---

## 2. Shared Config — `open_order_timeout_s` field

### 2.1 Add `open_order_timeout_s` to `DirectionalRuntimeConfig`
- File: `hbot/controllers/runtime/directional_config.py`
- Add: `open_order_timeout_s: int = Field(default=0, ge=0, description="Seconds before unfilled limit entry orders are cancelled. 0=disabled.")`
- Position: after other timing-related fields

### 2.2 (Optional) Add `open_order_timeout_s` to `EppV24Config`
- Only if MM bots need it in the future
- For now, can defer — bot1 uses market orders

---

## 3. Centralized Entry Timeout in Shared Adapter (shared: `hbot/controllers/runtime/market_making_core.py`)

### 3.1 Add entry-timeout filter to `executors_to_refresh`
- Read `open_order_timeout_s` from `controller.config` via `getattr(controller.config, "open_order_timeout_s", 0)`
- Inside the `if not reconnect_refresh_suppressed:` block (critical: must be suppressed during reconnect):
  - If `open_order_timeout_s > 0`:
    - Filter acknowledged executors: `is_active=True`, `is_trading=False`, `getattr(x, "order_id", "") != ""`, `now - x.timestamp > open_order_timeout_s`
    - Build `StopExecutorAction` list for these executors
  - Add to `actions` list

### 3.2 Add stale-filter guard for acknowledged executors with entry timeout
- When `open_order_timeout_s > 0`, modify the stale filter lambda to EXCLUDE acknowledged executors within the grace window:
  ```python
  grace_window = max(open_order_timeout_s, stale_age_s) + stale_age_s
  # Stale filter becomes:
  lambda x: (
      not x.is_trading
      and x.is_active
      and now - x.timestamp > stale_age_s
      and not (  # guard for acknowledged executors with entry timeout
          open_order_timeout_s > 0
          and getattr(x, "order_id", "")
          and now - x.timestamp <= grace_window
      )
  )
  ```
- When `open_order_timeout_s == 0`, the inner guard evaluates to `False` → no change to existing behavior

### 3.3 Deduplicate actions by `executor_id`
- Before returning, deduplicate `actions` list:
  ```python
  seen_ids = set()
  deduped = []
  for action in actions:
      eid = getattr(action, "executor_id", None)
      if eid not in seen_ids:
          seen_ids.add(eid)
          deduped.append(action)
  actions = deduped
  ```
- This also covers existing potential overlap between `stale_executors`, `stuck_executors`, and `_pending_stale_cancel_actions` — improvement over current code

### 3.4 Add logging for entry-timeout stops
- Log at INFO level when an executor is stopped due to entry timeout:
  ```
  ENTRY_TIMEOUT_CANCEL: executor_id=%s order_id=%s age_s=%.1f open_order_timeout_s=%d
  ```

---

## 4. Supervisory Mixin Guard (shared: `hbot/controllers/runtime/kernel/supervisory_mixin.py`)

### 4.1 Guard `_cancel_stale_orders` for entry timeout
- Read `open_order_timeout_s` from `getattr(self.config, "open_order_timeout_s", 0)`
- When `open_order_timeout_s > 0`, compute `guard_age = max(open_order_timeout_s, stale_age_s) + stale_age_s`
- In the order cancellation loop: if `(now_epoch - created_ts) < guard_age`, skip the order (don't cancel)
- This only affects orders with valid `created_ts > 0` (orders with `created_ts <= 0` are already skipped by existing logic)

---

## 5. Bot7 Lane — Minimal Config Wiring (bot lane: `hbot/controllers/bots/bot7/pullback_v1.py`)

### 5.1 Remove `executor_refresh_time` override for entry timeout
- In `build_runtime_execution_plan`, DELETE the block:
  ```python
  if limit_entry and side != "off":
      entry_timeout = int(getattr(self.config, "pb_entry_timeout_s", 30))
      self._runtime_levels.executor_refresh_time = entry_timeout
  ```
- The line `self._runtime_levels.executor_refresh_time = int(data_context.regime_spec.refresh_s)` earlier in the method remains (regime-driven value)

### 5.2 Map `pb_entry_timeout_s` → `open_order_timeout_s`
- In `PullbackV1Config.__init__` or `model_post_init`, add:
  ```python
  if self.pb_entry_timeout_s and not self.open_order_timeout_s:
      self.open_order_timeout_s = self.pb_entry_timeout_s
  ```
- Or: in `build_runtime_execution_plan`, set `self.config.open_order_timeout_s = int(getattr(self.config, "pb_entry_timeout_s", 30))` once
- Choose whichever is cleaner given `PullbackV1Config` inheritance chain (it extends `DirectionalRuntimeConfig` which now has the field)

### 5.3 Verify `_resolve_quote_side_mode` stale actions are unaffected
- Review that `_pending_stale_cancel_actions` extensions in `_resolve_quote_side_mode` (for side changes, mode=off transitions) are not disrupted
- These use `_cancel_stale_side_executors` and `_cancel_active_quote_executors` which target executors by `level_id` / side — orthogonal to entry timeout
- No code change expected — just verification

### 5.4 Verify `_force_cancel_orphaned_orders` is unaffected
- This method cancels connector orders not tied to active executors — orthogonal
- No code change expected — just verification

---

## 6. Paper Engine Probe Accuracy (shared: diagnostic improvement)

### 6.1 Update `POS_EXEC_TRACE` probe
- When the executor reports `engine_open` / `engine_inflight`, use the executor's `order_id` (now available from D1) to query the paper engine for the actual order state
- If `order_id` is not yet set, report `ack_pending=True`
- File: wherever the probe is emitted (likely in the executor or in `v2_with_controllers.py`)

---

## 7. Tests — Shared Infrastructure

### 7.1 Test: `_fire_accept_event` fires `BuyOrderCreatedEvent` for buy `OrderAccepted`
- Create `OrderAccepted(order_id="pe-test1", side="buy", ...)`
- Call `_fire_hb_events` with the event
- Assert strategy `trigger_event` was called with `BuyOrderCreatedEvent` containing correct fields

### 7.2 Test: `_fire_accept_event` fires `SellOrderCreatedEvent` for sell `OrderAccepted`
- Same as 7.1 with `side="sell"`

### 7.3 Test: Deduplication — second `OrderAccepted` for same `order_id` is no-op
- Fire `_fire_hb_events` twice with same `OrderAccepted` (same `order_id`)
- Assert `trigger_event` called ONCE

### 7.4 Test: Dedup reset — after `OrderCanceled`, same `order_id` can fire again
- Fire `OrderAccepted(order_id="pe-test1")` → triggers event
- Fire `OrderCanceled(order_id="pe-test1")` → clears dedup
- Fire `OrderAccepted(order_id="pe-test1")` again → triggers event again
- Assert `trigger_event` called TWICE total for acceptance

### 7.5 Test: `OrderRejected` does NOT fire acceptance event
- Fire `_fire_hb_events` with `OrderRejected`
- Assert no `BuyOrderCreatedEvent` / `SellOrderCreatedEvent`

### 7.6 Test: Runtime order upserted on acceptance
- Fire `_fire_hb_events` with `OrderAccepted`
- Assert `strategy._paper_exchange_runtime_orders[connector][order_id]` exists with correct fields

### 7.7 Test: Entry timeout — acknowledged executor stopped after `open_order_timeout_s`
- Mock controller with `open_order_timeout_s=30`, one active executor: `is_trading=False`, `is_active=True`, `order_id="pe-test1"`, `timestamp=now-35`
- Call `executors_to_refresh()`
- Assert `StopExecutorAction(executor_id=...)` in returned actions

### 7.8 Test: Entry timeout — acknowledged executor NOT stopped before `open_order_timeout_s`
- Same setup but `timestamp=now-20` (only 20s old)
- Assert no `StopExecutorAction` for entry timeout

### 7.9 Test: Entry timeout — unacknowledged executor NOT targeted by entry timeout
- Executor with `order_id=""`, `is_trading=False`, `is_active=True`, `open_order_timeout_s=30`, age=35s
- Assert entry-timeout logic does NOT emit stop (executor falls through to stuck detection)

### 7.10 Test: Stale-filter guard — acknowledged executor within grace window not flagged stale
- `stale_age_s=30`, `open_order_timeout_s=30`, executor: `order_id="pe-test1"`, `is_trading=False`, `is_active=True`, age=45s
- Grace window = `max(30,30) + 30 = 60s`
- Assert executor NOT in stale list (45 < 60)
- Assert executor IS in entry-timeout list (45 > 30)

### 7.11 Test: Stale-filter guard inert when `open_order_timeout_s=0`
- `stale_age_s=30`, `open_order_timeout_s=0`, executor: `order_id="pe-test1"`, `is_trading=False`, `is_active=True`, age=35s
- Assert executor IS flagged stale (existing behavior unchanged)

### 7.12 Test: Action deduplication
- Create scenario where executor appears in both entry-timeout and stale lists
- Assert exactly ONE `StopExecutorAction` in returned actions

### 7.13 Test: Reconnect suppression skips entry timeout
- `_in_reconnect_refresh_suppression_window` returns `True`
- Executor past `open_order_timeout_s`
- Assert no `StopExecutorAction` returned

### 7.14 Test: `_cancel_stale_orders` guard respects entry timeout
- `open_order_timeout_s=30`, order age=25s
- Assert order NOT cancelled by `_cancel_stale_orders`
- Order age=90s → assert order IS cancelled

### 7.15 Test: Fallback — unacked executor escalates to stuck/SOFT_PAUSE
- `open_order_timeout_s=30`, executor with no `order_id`, age > `ack_timeout_s`
- Assert executor flagged stuck (not entry-timeout)
- Assert `_consecutive_stuck_ticks` incremented

---

## 8. Tests — Bot Lane (config mapping only)

### 8.1 Test: `pb_entry_timeout_s` maps to `open_order_timeout_s`
- Create `PullbackV1Config(pb_entry_timeout_s=30)`
- Assert `config.open_order_timeout_s == 30`

### 8.2 Test: `executor_refresh_time` NOT overridden by entry timeout
- Call `build_runtime_execution_plan` with limit entry, regime `refresh_s=30`, `pb_entry_timeout_s=30`
- Assert `_runtime_levels.executor_refresh_time == 30` (from regime, not from entry timeout — same value but set by correct source)
- Call again with regime `refresh_s=120`, `pb_entry_timeout_s=30`
- Assert `_runtime_levels.executor_refresh_time == 120` (regime value, NOT 30)

### 8.3 Test: `_resolve_quote_side_mode` stale cancellation still works
- Transition side from "buy" to "off"
- Assert `_pending_stale_cancel_actions` extended with appropriate `StopExecutorAction`s

---

## 9. Integration Smoke Test

### 9.1 End-to-end: bot7 limit entry fills within timeout
- Set up paper engine with bot7 config: `pb_entry_timeout_s: 30`, regime "up" with `refresh_s: 30`
- Place limit buy order at favorable price
- Assert `BuyOrderCreatedEvent` fired (D1)
- Assert order fills before 30s
- Assert no premature `StopExecutorAction`

### 9.2 End-to-end: bot7 limit entry times out correctly
- Set up paper engine with bot7 config: `pb_entry_timeout_s: 30`
- Place limit buy order at unfavorable price (will not fill)
- Assert `BuyOrderCreatedEvent` fired
- Assert `StopExecutorAction` after ~30s from shared adapter
- Assert executor stopped cleanly

### 9.3 End-to-end: bot1 MM unaffected
- Run bot1 config (market orders, `open_order_timeout_s=0`)
- Assert no entry timeout logic triggered
- Assert existing stale/stuck behavior unchanged

---

## 10. Framework Boundary — Encapsulate `_pending_stale_cancel_actions` (Phase 2a)

### 10.1 Add `enqueue_stale_cancels` and `replace_stale_cancels` to `SharedRuntimeKernel`
- File: `hbot/controllers/runtime/kernel/controller.py` (near line 364 where `_pending_stale_cancel_actions` is initialized)
- Add:
  ```python
  def enqueue_stale_cancels(self, actions: list) -> None:
      self._pending_stale_cancel_actions.extend(actions)

  def replace_stale_cancels(self, actions: list) -> None:
      self._pending_stale_cancel_actions = list(actions)
  ```

### 10.2 Update `quoting_mixin.py` callers
- File: `hbot/controllers/runtime/kernel/quoting_mixin.py`
- Line 139: Replace `self._pending_stale_cancel_actions.extend(` with `self.enqueue_stale_cancels(`
- Line 143: Replace `self._pending_stale_cancel_actions.extend(` with `self.enqueue_stale_cancels(`

### 10.3 Update `regime_mixin.py` caller
- File: `hbot/controllers/runtime/kernel/regime_mixin.py`
- Line 125: Replace `self._pending_stale_cancel_actions = self._cancel_stale_side_executors(` with `self.replace_stale_cancels(self._cancel_stale_side_executors(`
- Close the parenthesis: add `)` at line 127 (after the `regime_spec.one_sided,` arg)

### 10.4 Update `pullback_v1.py` callers (bot7)
- File: `hbot/controllers/bots/bot7/pullback_v1.py`
- Line 1620: Replace `self._pending_stale_cancel_actions.extend(` with `self.enqueue_stale_cancels(`
- Line 1626: Replace `self._pending_stale_cancel_actions.extend(` with `self.enqueue_stale_cancels(`

### 10.5 Update `ift_jota_v1.py` callers (bot5)
- File: `hbot/controllers/bots/bot5/ift_jota_v1.py`
- Line 281: Replace `self._pending_stale_cancel_actions.extend(` with `self.enqueue_stale_cancels(`
- Line 295: Replace `self._pending_stale_cancel_actions.extend(` with `self.enqueue_stale_cancels(`

### 10.6 Update `cvd_divergence_v1.py` callers (bot6)
- File: `hbot/controllers/bots/bot6/cvd_divergence_v1.py`
- Line 420: Replace `self._pending_stale_cancel_actions.extend(` with `self.enqueue_stale_cancels(`
- Line 427: Replace `self._pending_stale_cancel_actions.extend(` with `self.enqueue_stale_cancels(`
- Line 435: Replace `self._pending_stale_cancel_actions.extend(` with `self.enqueue_stale_cancels(`

---

## 11. Framework Boundary — Formalize `_strategy_extra_actions` Hook (Phase 2b)

### 11.1 Add `_strategy_extra_actions` hook to `SharedRuntimeKernel`
- File: `hbot/controllers/runtime/kernel/controller.py`
- Add default hook method:
  ```python
  def _strategy_extra_actions(self) -> list:
      """Hook for bot lanes to inject additional CreateExecutorActions. Default: empty."""
      return []
  ```

### 11.2 Standardize `determine_executor_actions` in bot7
- File: `hbot/controllers/bots/bot7/pullback_v1.py`
- Line 249: Refactor the current override:
  ```python
  # BEFORE:
  def determine_executor_actions(self) -> list:
      actions = super().determine_executor_actions()
      if self._pb_pending_actions:
          actions.extend(self._pb_pending_actions)
          self._pb_pending_actions.clear()
      return actions

  # AFTER:
  def determine_executor_actions(self) -> list:
      actions = super().determine_executor_actions()
      actions.extend(self._strategy_extra_actions())
      return actions

  def _strategy_extra_actions(self) -> list:
      actions = self._pb_pending_actions[:]
      self._pb_pending_actions.clear()
      return actions
  ```

---

## 12. Framework Boundary — Eliminate `_runtime_levels` Mutation (Phase 2c)

### 12.1 Verify adapter sets `executor_refresh_time` from regime
- File: `hbot/controllers/runtime/market_making_core.py` — read `build_execution_plan` method
- Confirm it sets `controller._runtime_levels.executor_refresh_time = int(data_context.regime_spec.refresh_s)` (or equivalent)
- If confirmed, bot7's line 1675 is redundant

### 12.2 Remove bot7's duplicate `executor_refresh_time` set
- File: `hbot/controllers/bots/bot7/pullback_v1.py`
- Line 1675: DELETE `self._runtime_levels.executor_refresh_time = int(data_context.regime_spec.refresh_s)`

### 12.3 Add `super()` call to bot7's `build_runtime_execution_plan`
- File: `hbot/controllers/bots/bot7/pullback_v1.py`
- At the top of `build_runtime_execution_plan`, add: `super().build_runtime_execution_plan(execution_plan, data_context)`
- Verify that the adapter's `build_execution_plan` (called by super) does not set values that conflict with bot7's subsequent spread/sizing logic

---

## 13. Framework Boundary — Encapsulate `_recently_issued_levels` (Phase 2d)

### 13.1 Add `_reset_issued_levels` method to `SharedRuntimeKernel`
- File: `hbot/controllers/runtime/kernel/controller.py`
- Add:
  ```python
  def _reset_issued_levels(self) -> None:
      self._recently_issued_levels = {}
  ```

### 13.2 Update bot7 caller
- File: `hbot/controllers/bots/bot7/pullback_v1.py`
- Line 1593: Replace `self._recently_issued_levels = {}` with `self._reset_issued_levels()`

---

## 14. Framework Boundary — Replace Config Mutation (Phase 2e)

### 14.1 Add typed field to `PullbackV1Config`
- File: `hbot/controllers/bots/bot7/pullback_v1.py` (where `PullbackV1Config` is defined)
- Add field: `_pb_dynamic_tbc: Optional[TripleBarrierConfig] = Field(default=None, exclude=True)`
- Ensure `TripleBarrierConfig` is imported (verify it's already imported for other config usage)

### 14.2 Replace `object.__setattr__` calls
- File: `hbot/controllers/bots/bot7/pullback_v1.py`
- Line 460: Replace `object.__setattr__(self.config, "_pb_dynamic_tbc", dynamic_tbc)` with `self.config._pb_dynamic_tbc = dynamic_tbc`
- Line 464: Replace `object.__setattr__(self.config, "_pb_dynamic_tbc", None)` with `self.config._pb_dynamic_tbc = None`

---

## 15. Architectural Contract Tests (Phase 3)

### 15.1 Create `test_bot_lane_boundary.py`
- File: `hbot/tests/architecture/test_bot_lane_boundary.py`
- Scan all `.py` files under `hbot/controllers/bots/` (recursively)
- Follow existing architecture test patterns (see `hbot/tests/architecture/` for reference)

### 15.2 Test: No `_runtime_levels` mutation in bot lanes
- Scan for pattern: `_runtime_levels\.\w+\s*=` (attribute assignment on `_runtime_levels`)
- Exclude comment lines (lines starting with `#` after stripping)
- Assert zero matches across all bot lane files

### 15.3 Test: No direct `_pending_stale_cancel_actions` access in bot lanes
- Scan for pattern: `\._pending_stale_cancel_actions` (any attribute access)
- Exclude comment lines
- Assert zero matches across all bot lane files

### 15.4 Test: No `object.__setattr__` on config in bot lanes
- Scan for pattern: `object\.__setattr__\s*\(\s*self\.config`
- Exclude comment lines
- Assert zero matches across all bot lane files

### 15.5 Test: No direct `_recently_issued_levels` assignment in bot lanes
- Scan for pattern: `self\._recently_issued_levels\s*=\s*\{` (direct dict assignment)
- Exclude comment lines
- Assert zero matches across all bot lane files

---

## 16. Tests — Framework Boundary (Phase 2)

### 16.1 Test: `enqueue_stale_cancels` extends the queue
- Create `SharedRuntimeKernel` mock with empty `_pending_stale_cancel_actions`
- Call `enqueue_stale_cancels([action1, action2])`
- Assert `_pending_stale_cancel_actions == [action1, action2]`
- Call again with `[action3]`
- Assert `_pending_stale_cancel_actions == [action1, action2, action3]`

### 16.2 Test: `replace_stale_cancels` replaces the queue
- Create mock with `_pending_stale_cancel_actions = [action1, action2]`
- Call `replace_stale_cancels([action3])`
- Assert `_pending_stale_cancel_actions == [action3]`

### 16.3 Test: `_strategy_extra_actions` default returns empty
- Create `SharedRuntimeKernel` instance
- Assert `_strategy_extra_actions() == []`

### 16.4 Test: `_reset_issued_levels` clears the dict
- Set `_recently_issued_levels = {"key": 1.0}`
- Call `_reset_issued_levels()`
- Assert `_recently_issued_levels == {}`

### 16.5 Test: `PullbackV1Config._pb_dynamic_tbc` field exists and excluded
- Create `PullbackV1Config` with defaults
- Assert `config._pb_dynamic_tbc is None`
- Set `config._pb_dynamic_tbc = some_tbc`
- Assert `"_pb_dynamic_tbc" not in config.model_dump()`

### 16.6 Test: Bot7 `_strategy_extra_actions` drains pending actions
- Create `PullbackV1` instance with `_pb_pending_actions = [action1, action2]`
- Call `_strategy_extra_actions()`
- Assert returns `[action1, action2]`
- Assert `_pb_pending_actions == []`

### 16.7 Test: Bot7 `build_runtime_execution_plan` does NOT set `executor_refresh_time`
- Call `build_runtime_execution_plan` with regime `refresh_s=120`, `pb_entry_timeout_s=30`
- Verify `_runtime_levels.executor_refresh_time` is set by the adapter (via `super()`), not by bot7
- Assert value is `120` (regime-driven, not `30`)
