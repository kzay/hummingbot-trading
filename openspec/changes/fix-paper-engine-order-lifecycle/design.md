## Context

Bot7's pullback strategy places limit entry orders into the paper engine but never gets fills. The investigation traced a three-part structural defect:

1. **Missing event translation**: `hb_event_fire.py` handles `OrderFilled`, `OrderCanceled`, `OrderRejected` but silently drops `OrderAccepted`. The Hummingbot framework never receives `BuyOrderCreatedEvent`/`SellOrderCreatedEvent` for paper orders, so `PositionExecutor` never acknowledges its order and `is_trading` stays `False`.

2. **Overloaded config parameter**: `pullback_v1.py` sets `_runtime_levels.executor_refresh_time = pb_entry_timeout_s` (30s) to control limit entry expiration. But `market_making_core.executors_to_refresh` uses `stale_age_s = executor_refresh_time`, making 30s both the timeout *and* the maximum order lifespan.

3. **Paper-only visibility gap**: `PositionExecutor` trace probes report `engine_open=0 engine_inflight=0` right after placement because the bridge doesn't track paper orders in the framework's `_order_tracker`.

Current code flow:
```
pullback_v1.build_runtime_execution_plan() → set executor_refresh_time = 30
  → determine_executor_actions() → CreateExecutorAction
  → PositionExecutor.place_order() → bridge._patched_order()
    → PaperDesk.submit_order() → OrderAccepted (DROPPED by _fire_hb_events)
  → [30s later] executors_to_refresh() sees is_trading=False, age>30
    → StopExecutorAction → cancel before fill
```

All bots using limit entries in paper mode are affected. The fix must be backward-compatible with existing MM bots (bot1) and other directional bots.

**Architectural principle**: Trade execution lifecycle (order acknowledgment, entry timeout, stale reconciliation) is **shared infrastructure**. Bot lanes declare intent via config fields; the shared adapter enforces the mechanics. No bot lane should implement timeout bookkeeping or mutate `executor_refresh_time` for entry timeout purposes.

## Goals / Non-Goals

**Goals:**
- Paper orders receive the same event lifecycle as live orders (accepted → filled/cancelled)
- Entry timeout is a **centralized shared-adapter concern**, configurable via a single config field (`open_order_timeout_s`) on the shared config base
- Stale-executor reconciliation correctly distinguishes "pending limit entry" from "zombie executor"
- Zero behavioral change for market-making bots (bot1) and directional bots that don't use limit entries (bot5, bot6)
- Any future bot using limit entries inherits timeout management by setting one config field — zero per-lane plumbing
- Fix is forward-compatible with eventual live trading migration

**Non-Goals:**
- Rewriting the paper engine matching or latency model
- Changing the `TripleBarrierConfig` upstream class (owned by Hummingbot core)
- Adding a new timeout field to upstream `PositionExecutorConfig`
- Fixing the MQTT bridge reconnection issue (separate infra problem)
- Changing paper engine fill semantics or latency simulation
- Handling `CancelRejected`, `EngineError`, `OrderExpired` events (separate scope)

## Decisions

### D1: Fire `BuyOrderCreatedEvent`/`SellOrderCreatedEvent` in the bridge for `OrderAccepted`

**Decision**: Add a `_fire_accept_event` handler in `hb_event_fire.py` that translates `OrderAccepted` (from `simulation.types`, NOT `event_schemas.py`) into `BuyOrderCreatedEvent`/`SellOrderCreatedEvent` and dispatches it via the strategy's event trigger. Also ensure the order is tracked in the bridge's runtime order store (`_paper_exchange_runtime_orders`).

**Critical detail — deduplication**: With insert latency > 0, the matching engine emits `OrderAccepted` **twice** for the same `order_id`: once at submission (synchronous return from `submit_order`) and again when the latency queue drains in `tick()`. Both flow through `_fire_hb_events`. The handler MUST deduplicate by `order_id` — track already-fired acceptance `order_id`s in a set on `bridge_state` (or on `strategy`) and skip the second event. Alternatively, only fire on the first occurrence per `order_id`.

**Critical detail — shadow vs active mode**: In shadow mode, `_patched_order` calls `desk.submit_order()` then `_fire_hb_events` with the result. In active mode, `_patched_order` does NOT call `desk.submit_order` — it generates an `order_id`, upserts into runtime orders as `pending_create`, and returns without firing `_fire_hb_events`. For active mode, acceptance events arrive asynchronously via the paper exchange stream consumed in `drive_desk_tick` → `_consume_paper_exchange_events`. The `_fire_accept_event` handler must work for both paths.

**Critical detail — imports**: `BuyOrderCreatedEvent` and `SellOrderCreatedEvent` are NOT currently imported in `hb_event_fire.py`. They must be imported from the Hummingbot event types. The `OrderAccepted` import comes from `simulation.types`, not `platform_lib.contracts.event_schemas`.

**Critical detail — `EventSubscriber` protocol**: The current `_dispatch_to_subscribers` only handles `on_fill`, `on_cancel`, `on_reject`. Adding `on_accept` to the subscriber protocol is OPTIONAL for this change — the primary fix path is the HB event fire. If added, the protocol contract in `event_subscriber.py` (or equivalent) must be extended.

**Ownership**: Shared infrastructure (`hbot/simulation/bridge/`). Applies to all bots in paper mode.

**Rationale**: This is the minimal fix that closes the event lifecycle gap. The `PositionExecutor` already listens for `BuyOrderCreatedEvent`/`SellOrderCreatedEvent` to track its open order. Once the framework knows the order exists, `executor.order_id` will be populated, which is the signal the stale-filter needs.

**Alternatives considered**:
- *Patch `PositionExecutor` to track orders differently*: Invasive, touches upstream code, fragile across HB version upgrades.
- *Add a synthetic order tracker in the bridge*: Would duplicate state and create sync problems.

### D2: Centralized entry timeout in `MarketMakingRuntimeAdapter.executors_to_refresh`

**Decision**: Add a shared config field `open_order_timeout_s` (default `0` = disabled) to `DirectionalRuntimeConfig` and optionally `EppV24Config`. In `executors_to_refresh`, when `open_order_timeout_s > 0`, the adapter itself identifies acknowledged executors (`order_id` is set, `is_trading=False`) that have exceeded `open_order_timeout_s` and emits `StopExecutorAction` for them. Bot lanes do **not** implement timeout bookkeeping — they set config and the shared adapter handles the rest.

For bot7: `pullback_v1.py` removes the `executor_refresh_time` override and instead maps `pb_entry_timeout_s` → `open_order_timeout_s` (either via config aliasing or a one-liner in `build_runtime_execution_plan`). The `_runtime_levels.executor_refresh_time` stays at the regime-driven `refresh_s` value.

**Critical detail — `order_id` access on ExecutorInfo**: `ExecutorInfo` is duck-typed (no formal class in this repo). The `_is_unacked_executor` helper already uses `getattr(executor, "order_id", "")` safely. The new entry-timeout filter MUST also use `getattr` to avoid `AttributeError` on executor objects that might not have `order_id`.

**Critical detail — reconnect suppression**: When `_in_reconnect_refresh_suppression_window` returns `True`, the method skips all stale/stuck logic. The entry-timeout logic MUST also be skipped during reconnect suppression to maintain consistency — otherwise, entry-timed-out executors could be stopped while the connector is reconnecting.

**Critical detail — action deduplication**: The returned `actions` list merges `stale_executors + stuck_executors + entry_timed_out + _pending_stale_cancel_actions`. An executor could appear in both `entry_timed_out` and `stale_executors` (if past both thresholds). Deduplicate by `executor_id` before returning.

**Critical detail — `spread_engine.py` mutation**: `spread_engine.py` also adjusts `_runtime_levels.executor_refresh_time` (clamp). This must NOT be affected by the change — since we're no longer overriding `executor_refresh_time` for entry timeout, this is naturally safe, but verify during implementation.

**Rationale**:
- **Single responsibility**: The shared adapter already owns `executors_to_refresh` — adding entry timeout here keeps all executor lifecycle decisions in one place.
- **Zero duplication**: Bot5/bot6 (and any future bot) never need to implement this; they just set `open_order_timeout_s: 45` in YAML and it works.
- **Strategy isolation**: Bot lanes don't touch `_runtime_levels.executor_refresh_time` or implement per-executor timers. They declare intent via config.
- **Testable**: One set of unit tests in the shared adapter covers all bots.

**Alternatives considered**:
- *Controller-level bookkeeping in each bot lane (previous design)*: Violates DRY, forces every future bot with limit entries to implement the same timeout logic. **Rejected per architectural principle.**
- *Add `open_order_timeout_s` to `TripleBarrierConfig`*: Would require upstream Hummingbot changes; we don't control that class.
- *Use `time_limit` in TripleBarrierConfig*: Controls *position* time limit (after fill), not the open order timeout. Different semantics.

### D3: Stale-filter guard for acknowledged executors (in shared adapter)

**Decision**: In `executors_to_refresh`, acknowledged executors (`order_id` is set via `getattr`) with `open_order_timeout_s > 0` are exempt from the generic stale filter while within `max(open_order_timeout_s, stale_age_s) + grace_s`. This guard is part of the shared adapter, not per-bot logic. The entry timeout from D2 is the primary mechanism for these executors; the stale filter is the fallback safety net with a generous grace window.

Grace defaults to `stale_age_s` (i.e., total window = `max(open_order_timeout_s, stale_age_s) + stale_age_s`), ensuring acknowledged limit entries are never caught by the stale sweep before the entry timeout fires.

**Critical detail — `_cancel_stale_orders` operates on connector orders, not executors**: `_cancel_stale_orders` in `supervisory_mixin.py` iterates `connector.get_open_orders()` and uses the ORDER's `creation_timestamp` (not the executor's `timestamp`). It doesn't use `_paper_exchange_runtime_orders`. The guard there needs the same `open_order_timeout_s` grace but applied to order-level age. If the paper engine doesn't populate `creation_timestamp` on its orders, this guard is irrelevant (orders with `created_ts <= 0` are already skipped).

When `open_order_timeout_s == 0` (disabled), the guard is inert — existing behavior is unchanged.

**Alternatives considered**:
- *Skip stale check entirely for acknowledged executors*: Risk of accumulating zombie executors if the timeout logic has a bug.
- *Hardcoded 2x multiplier*: Too rigid; the grace should scale with `stale_age_s` which varies by regime.

### D4: Paper engine probe accuracy

**Decision**: The `POS_EXEC_TRACE` probe for `engine_open` and `engine_inflight` will query the paper engine using the order's actual `order_id` (once available from D1). If the order is not yet acknowledged, the probe reports `ack_pending=True`.

**Rationale**: Diagnostic improvement. The current `engine_open=0` right after placement is misleading.

### D5: Encapsulate `_pending_stale_cancel_actions` behind methods

**Decision**: Add two methods on `SharedRuntimeKernel`:
```python
def enqueue_stale_cancels(self, actions: list) -> None:
    self._pending_stale_cancel_actions.extend(actions)

def replace_stale_cancels(self, actions: list) -> None:
    self._pending_stale_cancel_actions = list(actions)
```

All callers (quoting mixin, regime mixin, bot5/6/7) switch from direct list access to these methods. The `_pending_stale_cancel_actions` attribute remains on the instance (for the adapter's `executors_to_refresh` to drain) but is no longer accessed directly from bot lanes.

**Critical detail — `regime_mixin.py` uses assignment `=`, not `extend`**: Line 125 replaces the entire list. This is intentional — on regime side-change, previous pending cancels are discarded. `replace_stale_cancels` preserves this semantics.

**Ownership**: Shared infrastructure (`controller.py`). Callers: `quoting_mixin.py` (lines 139, 143), `regime_mixin.py` (line 125), `pullback_v1.py` (lines 1620, 1626), `ift_jota_v1.py` (lines 281, 295), `cvd_divergence_v1.py` (lines 420, 427, 435).

**Rationale**: Encapsulation. Bot lanes express "cancel these executors" intent through a method call; the framework owns the queue implementation. Enables future logging, validation, or deduplication at the queue level.

### D6: Formalize `_strategy_extra_actions()` hook

**Decision**: Add a hook on `SharedRuntimeKernel`:
```python
def _strategy_extra_actions(self) -> list:
    """Hook for bot lanes to inject additional CreateExecutorActions. Default: empty."""
    return []
```

In bot7's current `determine_executor_actions` override (line 249), replace the full override with an override of `_strategy_extra_actions`:
```python
def _strategy_extra_actions(self) -> list:
    actions = self._pb_pending_actions[:]
    self._pb_pending_actions.clear()
    return actions
```

The base `determine_executor_actions` (if controlled by this repo) or the existing override calls `super().determine_executor_actions()` then extends with `self._strategy_extra_actions()`. Since `determine_executor_actions` is from Hummingbot's base class (`MarketMakingControllerBase`), the override stays but delegates to the hook.

**Critical detail — `determine_executor_actions` is NOT in this repo**: It's defined on Hummingbot's `MarketMakingControllerBase`. Bot7's override calls `super()` then extends. The hook approach means bot7 still overrides `determine_executor_actions` but the override body becomes standardized: `super() + self._strategy_extra_actions()`. If we ever vendor/wrap the base class, the override moves to the kernel.

**Ownership**: Shared (`controller.py` for the default hook). Bot lane (`pullback_v1.py` for the override).

**Rationale**: Separates "what additional actions does this strategy need" from "how does the executor lifecycle work." The hook pattern is already used for `_extend_processed_data_before_log`.

### D7: Eliminate `_runtime_levels` mutation from bot lanes

**Decision**: Remove the duplicate `self._runtime_levels.executor_refresh_time = int(data_context.regime_spec.refresh_s)` from bot7's `build_runtime_execution_plan` (line 1675). The adapter's `build_execution_plan` already sets this value. Bot7 should call `super().build_runtime_execution_plan(execution_plan, data_context)` at the top of its override to let the adapter set regime-driven values, then only extend with strategy-specific spreads/sizing.

**Critical detail — call order verification**: `QuotingMixin.build_runtime_execution_plan` delegates to `adapter.build_execution_plan`. Bot7 overrides `build_runtime_execution_plan` at the controller level. Currently bot7 sets `executor_refresh_time` itself (line 1675) and does NOT call `super()`. After this change, bot7 must call `super().build_runtime_execution_plan(execution_plan, data_context)` first. Verify that the adapter's `build_execution_plan` sets `executor_refresh_time` from `data_context.regime_spec.refresh_s` — if it does, the bot7 line is redundant and safe to remove.

**Critical detail — Phase 1 removes the entry-timeout override (line 1785)**: Phase 1 already removes the `executor_refresh_time = entry_timeout` hack. Phase 2c removes the remaining `executor_refresh_time = refresh_s` line. After both, bot7 has zero `_runtime_levels` mutations.

**Ownership**: Bot lane (`pullback_v1.py`). Requires verifying shared adapter behavior.

### D8: Encapsulate `_recently_issued_levels` clearing

**Decision**: Add a method on `SharedRuntimeKernel`:
```python
def _reset_issued_levels(self) -> None:
    self._recently_issued_levels = {}
```

Bot7 (line 1593) replaces `self._recently_issued_levels = {}` with `self._reset_issued_levels()`.

**Rationale**: Prevents bot lanes from directly clearing internal tracking state. The method is trivial but establishes the boundary.

### D9: Replace dynamic config mutation with typed field

**Decision**: Add `_pb_dynamic_tbc: Optional[TripleBarrierConfig] = Field(default=None, exclude=True)` to `PullbackV1Config`. Bot7 replaces `object.__setattr__(self.config, "_pb_dynamic_tbc", ...)` (lines 460, 464) with direct assignment `self.config._pb_dynamic_tbc = ...` since the field now exists on the config type.

**Critical detail — `exclude=True`**: The field is excluded from serialization/YAML — it's a runtime-only computed field. Pydantic `exclude=True` ensures it doesn't appear in `model_dump()`.

**Critical detail — two call sites**: Line 460 (success path: set to computed TBC) and line 464 (error path: set to `None`).

**Rationale**: `object.__setattr__` bypasses Pydantic's model machinery and type checking. A proper field makes the intent explicit and type-safe.

### D10: Architectural contract tests

**Decision**: Add `hbot/tests/architecture/test_bot_lane_boundary.py` with AST/regex-based contract tests that scan all Python files under `hbot/controllers/bots/` for forbidden patterns:

1. `_runtime_levels.executor_refresh_time =` — bot lanes must not mutate executor refresh time
2. `._pending_stale_cancel_actions` — bot lanes must use `enqueue_stale_cancels()` / `replace_stale_cancels()`
3. `object.__setattr__(self.config,` — bot lanes must use typed config fields
4. `_recently_issued_levels = {` — bot lanes must use `_reset_issued_levels()`

Tests use the same pattern as existing architecture tests in `hbot/tests/architecture/` (file scanning with regex/AST).

**Rationale**: Prevents regression. The Phase 2 refactors are mechanical but fragile without guardrails. Contract tests catch future developers who unknowingly reach into shared internals.

## Risks / Trade-offs

**[Risk: Double `OrderAccepted` with insert latency]** The matching engine emits `OrderAccepted` at submission AND when the latency queue drains. Both events reach `_fire_hb_events`.
→ **Mitigation**: Deduplicate by `order_id` in the acceptance handler. Track fired acceptances in a set. Second event for same `order_id` is a no-op.

**[Risk: Shadow vs Active mode divergence]** Shadow mode fires events synchronously from `_patched_order`. Active mode fires asynchronously from paper exchange stream consumption.
→ **Mitigation**: The `_fire_accept_event` handler is called from `_fire_hb_events` which is used by both paths. The handler itself is mode-agnostic.

**[Risk: Timing of BuyOrderCreatedEvent dispatch]** The `_fire_hb_events` call happens synchronously in `_patched_order`, before the paper engine's latency simulation moves the order from `PENDING_SUBMIT` to `OPEN`.
→ **Mitigation**: Matches live exchange behavior where `BuyOrderCreatedEvent` fires on submission acknowledgment. `PositionExecutor` already handles this.

**[Risk: Entry timeout resolution limited by tick interval]** `executors_to_refresh` runs once per `determine_executor_actions` call. If `refresh_s` is 120s (neutral regime), an entry timeout of 30s could wait up to 150s.
→ **Mitigation**: In neutral regime, pullback signals are `side=off` so no limit entries are placed. In up/down regimes, `refresh_s: 30` gives sub-minute resolution. This is inherent to the tick-based architecture and acceptable.

**[Risk: `ExecutorInfo` duck typing]** `order_id` may not exist on all executor info objects. Code uses `getattr(executor, "order_id", "")`.
→ **Mitigation**: New entry-timeout filter MUST use `getattr` pattern, not direct attribute access. Follow the existing `_is_unacked_executor` pattern.

**[Risk: `_consecutive_stuck_ticks` escalation interaction]** If entry-timed-out executors are (correctly) not caught by the stuck filter, the stuck-tick counter stays at 0. But if D1 fails (acceptance events not fired), executors remain unacked and DO trigger stuck detection after `ack_timeout_s`, eventually escalating to `SOFT_PAUSE` via `risk_mixin.py`.
→ **Mitigation**: This is actually a safety feature. If D1 breaks, the system falls back to existing stuck-detection escalation. Document this as expected fallback behavior.

**[Risk: Reconnect suppression window]** During reconnect, all stale/stuck/entry-timeout stops are suppressed.
→ **Mitigation**: Entry timeout logic must be inside the `if not reconnect_refresh_suppressed:` block, matching existing behavior.

**[Risk: Double `StopExecutorAction` for same executor]** An executor past both `open_order_timeout_s` and `stale_age_s + grace` could appear in both `entry_timed_out` and `stale_executors` lists.
→ **Mitigation**: Deduplicate the final `actions` list by `executor_id` before returning.

**[Risk: Backward compatibility with bot1 MM]** Bot1 uses market orders and never sets `open_order_timeout_s`.
→ **Mitigation**: `open_order_timeout_s` defaults to `0` (disabled). When disabled, D2 is inert, D3's guard is inert. Zero behavioral change.

**[Risk: Bot5/Bot6 compatibility]** They don't use limit entries.
→ **Mitigation**: `open_order_timeout_s` defaults to `0` in `DirectionalRuntimeConfig`. Zero behavioral change.

**[Risk: Existing `entry-quality` spec references the old mechanism]** The current spec says `pb_entry_timeout_s` SHALL set `executor_refresh_time`.
→ **Mitigation**: Delta spec modifies this requirement. External behavior (order cancelled after 30s if unfilled) remains identical.

**[Risk: `_pending_stale_cancel_actions` overlap]** Other mixins (quoting, regime, risk) enqueue `StopExecutorAction`s into `_pending_stale_cancel_actions`. These could target the same executor as entry-timeout or stale lists.
→ **Mitigation**: The final deduplication by `executor_id` covers this. Existing code already has this potential overlap (stale + pending) without dedup — this change improves it.

**[Risk: Phase 2c — `super().build_runtime_execution_plan()` call order]** Bot7 currently does NOT call `super()` in its `build_runtime_execution_plan`. Adding the `super()` call may set runtime levels that bot7 then overrides with spreads/sizing. If the adapter's `build_execution_plan` does more than set `executor_refresh_time` (e.g., sets spread values), bot7's subsequent spread logic must still take precedence.
→ **Mitigation**: Read the adapter's `build_execution_plan` method before implementing. If it sets values bot7 overrides, the `super()` call is safe. If it sets values bot7 does NOT override, verify they are correct for directional mode.

**[Risk: Phase 2b — `_strategy_extra_actions` timing]** The hook is called from within `determine_executor_actions`. If bot7 populates `_pb_pending_actions` in `build_runtime_execution_plan` (which runs before `determine_executor_actions`), the timing is safe. Verify no circular dependency.
→ **Mitigation**: Trace the call order in `v2_with_controllers.py` → `create_actions_proposal` → `determine_executor_actions`.

**[Risk: Phase 2a — `regime_mixin` replace semantics]** `replace_stale_cancels` uses `=` (replace). If other code between `_apply_regime` and `executors_to_refresh` also calls `enqueue_stale_cancels`, those additions would be lost. Verify that `_apply_regime` runs before quoting/side-mode logic.
→ **Mitigation**: Trace tick order: `update_processed_data` → `_apply_regime` → then quoting/side-mode. The regime replace runs first, subsequent enqueues add to the new list. This is the current behavior with direct assignment.

**[Risk: Phase 3 — false positives in contract tests]** Regex-based scanning could match comments or string literals containing the forbidden patterns.
→ **Mitigation**: Use targeted regex that matches assignment context (e.g., `self\._pending_stale_cancel_actions\.` not in comments). Or use AST-based analysis for precision. Follow existing architecture test patterns.

## Open Questions

None — all design decisions are informed by the deep investigation, the code review of all involved modules, and the architectural principle of centralized execution lifecycle. Implementation can proceed.
