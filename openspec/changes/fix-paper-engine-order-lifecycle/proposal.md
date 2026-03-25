## Why

Bot7's limit entry orders never fill in the paper engine. Every order placed by the pullback strategy is cancelled within one reconciliation tick (~55s) because the stale-executor detection uses the same 30s `pb_entry_timeout_s` value that was designed to give orders time to fill. The root cause is a three-part structural defect: (1) the paper bridge silently drops `OrderAccepted` events, so the Hummingbot framework never acknowledges paper orders, (2) `pb_entry_timeout_s` is overloaded onto `executor_refresh_time` which controls both entry timeout and stale-executor reconciliation, creating a zero-margin race condition, and (3) the `PositionExecutor` sees unfilled limit orders as `is_trading=False` indefinitely, making them permanent targets for the stale sweep. This affects all paper-traded bots using limit entries, not just bot7.

**Architectural principle**: Trade execution lifecycle — order acknowledgment, entry timeout management, and stale-executor reconciliation — must be owned by the **shared runtime modules** (`market_making_core.py`, `directional_config.py`, `supervisory_mixin.py`, `hb_event_fire.py`), not scattered across individual bot lanes. Bot lanes should declare intent (e.g. "I want limit entries with 30s timeout") via config; the shared infrastructure enforces the mechanics.

## What Changes

- **Paper bridge fires `BuyOrderCreatedEvent` / `SellOrderCreatedEvent`** when the paper engine accepts an order, closing the event lifecycle gap that leaves executors in a phantom unacknowledged state. Includes **deduplication** of `OrderAccepted` events (the matching engine emits two per order when insert latency > 0) and **runtime order upsert** so the fill handler can resolve side/type. Works in both shadow mode (synchronous from `_patched_order`) and active mode (async from paper exchange stream). *(Shared: `hb_event_fire.py`, `hb_bridge.py`)*
- **Centralized entry timeout in the shared adapter**: `MarketMakingRuntimeAdapter.executors_to_refresh` gains a new `open_order_timeout_s` parameter (from config) that manages limit entry expiration independently of the stale reconciliation interval. This is **not** a bot-lane concern — any bot (MM or directional) that uses limit entries benefits automatically. *(Shared: `market_making_core.py`)*
- **New shared config field `open_order_timeout_s`**: Added to `DirectionalRuntimeConfig` (default `0` = disabled). Bot7's `pb_entry_timeout_s` maps to this field via its config class. Future bots using limit entries configure the same field — zero per-lane plumbing needed. *(Shared: `directional_config.py`, optionally `EppV24Config`)*
- **BREAKING**: `pullback_v1.py` no longer overrides `_runtime_levels.executor_refresh_time` with `pb_entry_timeout_s`. The regime-driven `refresh_s` (from `regime_specs_override` or top-level `executor_refresh_time`) controls stale reconciliation exclusively. The per-lane `executor_refresh_time` hack is removed entirely.
- **Stale-executor filter guard** centralized in `executors_to_refresh`: acknowledged executors (non-empty `order_id`) with `open_order_timeout_s > 0` are exempt from stale flagging while within the timeout + grace window. *(Shared: `market_making_core.py`)*
- **Action deduplication** in `executors_to_refresh`: the returned actions list is deduplicated by `executor_id` to prevent double stops when an executor appears in multiple lists (entry-timeout, stale, stuck, pending). *(Shared: `market_making_core.py`)*
- **Reconnect suppression consistency**: entry timeout logic is suppressed during reconnect windows alongside existing stale/stuck logic. *(Shared: `market_making_core.py`)*
- **`_cancel_stale_orders` guard** in supervisory mixin respects the same centralized timeout. *(Shared: `supervisory_mixin.py`)*
- Fix the paper engine probe in `PositionExecutor` traces so `engine_open` / `engine_inflight` reflect the correct engine state.

### Critical Implementation Notes (from code review)
- **`OrderAccepted` is defined in `simulation.types`, NOT in `platform_lib.contracts.event_schemas`** — the import must come from the correct module.
- **`OrderAccepted` does NOT have a `trading_pair` field** — the handler must resolve it from `connector_name` mapping or `bridge_state` context.
- **`ExecutorInfo` is duck-typed** (no formal class) — all attribute access in filter lambdas must use `getattr` to avoid `AttributeError`.
- **`_fire_fill_event` resolves `trade_type` from multiple sources** (event field, then runtime orders store) — the acceptance handler should follow the same pattern.
- **`spread_engine.py` clamps `executor_refresh_time`** — this is orthogonal since we no longer override it for entry timeout, but implementer should verify no interaction.

### Phase 2 — Formalize the framework boundary

Bot lanes currently "reach into" shared infrastructure in 5 ways. Phase 2 formalizes each as a proper contract:

- **2a. Encapsulate `_pending_stale_cancel_actions`**: Replace direct list access (`self._pending_stale_cancel_actions.extend(...)`) with `self.enqueue_stale_cancels(actions)` method on `SharedRuntimeKernel`. The `regime_mixin` assignment (`=`) becomes `self.replace_stale_cancels(actions)`. Bot lanes and mixins call the method; the internal list is private. *(Shared: `controller.py`; callers: `quoting_mixin.py`, `regime_mixin.py`, `pullback_v1.py`, `ift_jota_v1.py`, `cvd_divergence_v1.py`)*
- **2b. Formalize `_strategy_extra_actions()` hook**: Bot7 overrides `determine_executor_actions` to inject trailing-stop/partial-take `CreateExecutorAction`s via `_pb_pending_actions`. Replace with a `_strategy_extra_actions() -> list` hook on `SharedRuntimeKernel` (default: empty list) called from `determine_executor_actions`. Bot7 overrides only the hook. *(Shared: `controller.py` or `quoting_mixin.py`; bot lane: `pullback_v1.py`)*
- **2c. Eliminate `_runtime_levels` mutation from bot lanes**: After Phase 1, bot7's entry timeout override is removed. The remaining `_runtime_levels.executor_refresh_time = int(data_context.regime_spec.refresh_s)` in bot7's `build_runtime_execution_plan` duplicates what the adapter already does. Remove the duplicate line; bot7 should call `super().build_runtime_execution_plan()` to let the adapter set regime-driven values, then extend with spreads/sizing only. *(Bot lane: `pullback_v1.py`)*
- **2d. Encapsulate `_recently_issued_levels` clearing**: Bot7 does `self._recently_issued_levels = {}` after orphan sweep. Replace with `self._reset_issued_levels()` method on the kernel. *(Shared: `controller.py`; bot lane: `pullback_v1.py`)*
- **2e. Replace dynamic config mutation**: Bot7 uses `object.__setattr__(self.config, "_pb_dynamic_tbc", ...)` to attach a dynamic `TripleBarrierConfig`. Replace with a proper typed field `_pb_dynamic_tbc: Optional[TripleBarrierConfig] = Field(default=None, exclude=True)` on `PullbackV1Config`. *(Bot lane: `pullback_v1.py` config class)*

### Phase 3 — Architectural contract tests

Add import/AST-based contract tests in `hbot/tests/architecture/` that prevent future boundary violations:
- No `_runtime_levels.executor_refresh_time =` in bot lane files
- No `._pending_stale_cancel_actions` direct access in bot lane files
- No `object.__setattr__(self.config,` in bot lane files
- No `_recently_issued_levels =` assignment in bot lane files

## Capabilities

### New Capabilities
- `paper-order-lifecycle`: Complete order lifecycle event translation in the paper bridge — acceptance, fill, cancel, reject — ensuring the Hummingbot framework tracks paper orders identically to live orders. *(Shared infrastructure)*
- `executor-entry-timeout`: Centralized entry timeout in `MarketMakingRuntimeAdapter.executors_to_refresh`, driven by the shared config field `open_order_timeout_s`. Any bot lane that sets this config value gets entry timeout management for free. *(Shared infrastructure)*
- `framework-boundary`: Formal contract between shared framework and bot lanes — encapsulated lifecycle queues, action hooks, read-only runtime levels, and typed config fields. Enforced by architectural contract tests. *(Shared infrastructure + architecture tests)*

### Modified Capabilities
- `entry-quality`: The "Entry timeout via executor refresh" requirement changes — `pb_entry_timeout_s` no longer overrides `executor_refresh_time`. Instead, the bot config maps `pb_entry_timeout_s` → `open_order_timeout_s` and the shared adapter handles the rest.

## Impact

### Shared Infrastructure (centralized changes)
- **`hbot/simulation/bridge/hb_event_fire.py`**: New `_fire_accept_event` handler for `OrderAccepted` → `BuyOrderCreatedEvent`/`SellOrderCreatedEvent`, with deduplication set on `bridge_state` and runtime order upsert. Dedup set cleared on cancel/fill/reject.
- **`hbot/simulation/bridge/hb_bridge.py`**: No code changes needed — `_patched_order` (shadow) and `drive_desk_tick` already call `_fire_hb_events` which will route to the new handler.
- **`hbot/controllers/runtime/market_making_core.py`**: `executors_to_refresh` gains entry timeout logic (acknowledged executors with `open_order_timeout_s > 0` are stopped after timeout, excluded from stale within grace window). Action deduplication by `executor_id`. Entry timeout suppressed during reconnect. Replaces per-lane bookkeeping.
- **`hbot/controllers/runtime/kernel/supervisory_mixin.py`**: `_cancel_stale_orders` respects the same centralized timeout.
- **`hbot/controllers/runtime/directional_config.py`**: New field `open_order_timeout_s: int = 0` on `DirectionalRuntimeConfig`.

### Bot Lanes (minimal, config-only changes)
- **`hbot/controllers/bots/bot7/pullback_v1.py`**: Remove `executor_refresh_time` override. Map `pb_entry_timeout_s` → `open_order_timeout_s` in config init or `build_runtime_execution_plan`. No custom timeout bookkeeping needed.
- **`hbot/controllers/bots/bot5/`, `hbot/controllers/bots/bot6/`**: Zero changes. They don't use limit entries; `open_order_timeout_s` defaults to `0` (disabled).
- **`hbot/data/bot7/conf/controllers/epp_v2_4_bot7_pullback_paper.yml`**: No schema change; `pb_entry_timeout_s` retains its meaning.

### Framework Boundary Formalization (Phase 2)
- **`hbot/controllers/runtime/kernel/controller.py`**: Add `enqueue_stale_cancels()`, `replace_stale_cancels()`, `_reset_issued_levels()` methods. Add `_strategy_extra_actions()` hook (default empty list).
- **`hbot/controllers/runtime/kernel/quoting_mixin.py`** (lines 139, 143): Replace `self._pending_stale_cancel_actions.extend(...)` with `self.enqueue_stale_cancels(...)`.
- **`hbot/controllers/runtime/kernel/regime_mixin.py`** (line 125): Replace `self._pending_stale_cancel_actions = ...` with `self.replace_stale_cancels(...)`.
- **`hbot/controllers/bots/bot7/pullback_v1.py`** (lines 1620, 1626): Replace `_pending_stale_cancel_actions.extend(...)` with `self.enqueue_stale_cancels(...)`. Remove `determine_executor_actions` override (line 249), implement `_strategy_extra_actions`. Remove duplicate `_runtime_levels.executor_refresh_time` set (line 1675). Replace `self._recently_issued_levels = {}` (line 1593) with `self._reset_issued_levels()`. Replace `object.__setattr__` (lines 460, 464) with typed field access.
- **`hbot/controllers/bots/bot5/ift_jota_v1.py`** (lines 281, 295): Replace `_pending_stale_cancel_actions.extend(...)` with `self.enqueue_stale_cancels(...)`.
- **`hbot/controllers/bots/bot6/cvd_divergence_v1.py`** (lines 420, 427, 435): Replace `_pending_stale_cancel_actions.extend(...)` with `self.enqueue_stale_cancels(...)`.
- **`PullbackV1Config`**: Add `_pb_dynamic_tbc: Optional[TripleBarrierConfig] = Field(default=None, exclude=True)`.

### Architecture Contract Tests (Phase 3)
- **`hbot/tests/architecture/test_bot_lane_boundary.py`**: New test file with 4 contract tests scanning bot lane files for forbidden patterns (`_runtime_levels.executor_refresh_time =`, `._pending_stale_cancel_actions`, `object.__setattr__(self.config,`, `_recently_issued_levels =`).

### Specs and Tests
- **`openspec/specs/entry-quality/spec.md`**: Updated requirement for centralized entry timeout.
- **`openspec/specs/framework-boundary/spec.md`**: New spec defining the formal contract between shared framework and bot lanes.
- **Test surface**: 15+ new unit tests in shared modules (bridge event dedup, acceptance dispatch, adapter entry timeout, stale-filter guard, action dedup, reconnect suppression, supervisory guard, fallback escalation). Bot-lane tests verify config mapping and `executor_refresh_time` independence. Integration smoke tests for end-to-end lifecycle. 4 new architecture contract tests enforce framework boundary.
