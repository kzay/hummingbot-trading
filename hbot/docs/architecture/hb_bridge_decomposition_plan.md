# hb_bridge.py Decomposition Plan

## Current State

| Metric | Value |
|---|---|
| File | `hbot/controllers/paper_engine_v2/hb_bridge.py` |
| Total lines | ~2,649 |
| Classes | `BridgeState` (L233–318) |
| Module-level functions | ~65 functions |
| Existing extractions | `signal_consumer.py`, `adverse_inference.py`, `hb_event_fire.py`, `budget_checker.py`, `connector_patches.py` |
| Module-level state | `_bridge_state` (BridgeState singleton), `_LATENCY_TRACKER`, `_REDIS_IO_POOL`, `_CANONICAL_CACHE` |

### Architecture Role

`hb_bridge.py` is the **only file** in `paper_engine_v2/` that imports Hummingbot types. It translates between the PaperDesk domain model and HB's connector/executor interface. It has two modes:

- **Shadow mode**: orders execute locally on PaperDesk, events published to Redis for observation
- **Active mode**: orders are published as commands to the `paper_exchange_service`, events consumed from Redis

---

## Method Inventory by Responsibility Group

### 1. Utilities & Normalization (Top of File)

| Function | Lines | Purpose |
|---|---|---|
| `_paper_command_constraints_metadata` | L90–131 | Extract trading rule constraints for command metadata |
| `_trace_paper_order` | L134–142 | Rate-limited order trace logging |
| `_order_type_text` | L145–146 | Normalize order type to uppercase string |
| `_normalize_position_action` | L149–161 | Convert HB position action to PaperDesk enum |
| `_normalize_position_action_hint` | L164–177 | Optional position action mapping |
| `_resolve_shadow_submit_price` | L180–222 | Resolve non-zero price for market orders in shadow mode |

### 2. Bridge State Management

| Function / Class | Lines | Purpose |
|---|---|---|
| `BridgeState` class | L233–318 | Encapsulates all mutable module-level state |
| `BridgeState.__init__` / `reset` | L265–289 | Initialize/reset 18 state attributes |
| `BridgeState.get_redis` | L291–317 | Lazy Redis client initialization |
| `_bridge_state` singleton | L320 | Process-wide mutable state instance |

### 3. Paper Exchange Mode Resolution

| Function | Lines | Purpose |
|---|---|---|
| `_get_signal_redis` | L333–335 | Delegate to BridgeState.get_redis |
| `_canonical_name` | L338–355 | Connector name canonicalization with cache |
| `_instance_env_suffix` | L358–360 | ENV var suffix from instance name |
| `_normalize_paper_exchange_mode` | L363–374 | Validate mode string (disabled/shadow/active/auto) |
| `_parse_env_bool` | L377–383 | Boolean ENV var parser |
| `_paper_exchange_service_only_for_instance` | L386–394 | Check per-instance service-only flag |
| `_paper_exchange_service_heartbeat_is_fresh` | L397–422 | Check heartbeat stream freshness |
| `_paper_exchange_auto_mode` | L425–451 | Resolve auto mode via heartbeat + cache |
| `_paper_exchange_cursor_key` | L454–467 | Per-instance Redis cursor key |
| `_bootstrap_paper_exchange_cursor` | L470–515 | One-time cursor initialization from persisted offset |
| `_paper_exchange_mode_for_instance` | L517–547 | Full mode resolution chain per instance |
| `_resolve_controller_for_command` | L550–588 | Find controller for connector/pair routing |
| `_paper_exchange_mode_for_route` | L591–593 | Mode for a specific connector/pair route |
| `_bridge_for_exchange_event` | L596–623 | Look up bridge dict for exchange event |

### 4. Active Mode Idempotency & Deduplication

| Function | Lines | Purpose |
|---|---|---|
| `_sync_handshake_key` | L626–627 | Build sync state cache key |
| `_active_submit_retry_ttl_s` | L630–637 | Submit retry TTL from ENV |
| `_active_submit_fingerprint` | L640–672 | Fingerprint for submit dedup |
| `_active_submit_order_id` | L675–724 | Generate/reuse idempotent order ID |
| `_active_cancel_retry_ttl_s` | L727–734 | Cancel retry TTL from ENV |
| `_active_cancel_fingerprint` | L737–751 | Fingerprint for cancel dedup |
| `_active_cancel_command_event_id` | L754–794 | Generate/reuse cancel event ID |
| `_active_cancel_all_retry_ttl_s` | L797–804 | Cancel-all retry TTL from ENV |
| `_active_cancel_all_fingerprint` | L807–827 | Fingerprint for cancel-all dedup |
| `_active_cancel_all_command_event_id` | L830–867 | Generate/reuse cancel-all event ID |

### 5. Runtime Order Tracking

| Function | Lines | Purpose |
|---|---|---|
| `_runtime_orders_store` | L870–879 | Get/create per-strategy order store |
| `_runtime_orders_bucket` | L882–890 | Get/create per-connector order bucket |
| `_runtime_order_trade_type` | L893–895 | Normalize side to BUY/SELL |
| `_canonical_runtime_order_state` | L898–906 | Normalize order state string |
| `_runtime_order_state_flags` | L909–915 | Derive is_done/is_open from state |
| `_upsert_runtime_order` | L918–981 | Create or update runtime order SimpleNamespace |
| `_prune_runtime_orders` | L984–1000 | Remove stale done orders |
| `_paper_exchange_state_snapshot_path` | L1003–1019 | Resolve snapshot file path |
| `_active_command_ttl_ms` | L1022–1037 | Per-command TTL resolution |
| `_hydrate_runtime_orders_from_state_snapshot` | L1040–1096 | Warm-start orders from disk snapshot |
| `_controller_tracked_order_ids` | L1099–1110 | Get executor-tracked order IDs |
| `_cancel_reconciled_ghost_orders` | L1113–1153 | Cancel orders not tracked by any executor |
| `_get_runtime_order_for_executor` | L1156–1180 | Look up runtime order by ID |

### 6. Sync Gate & Failure Policy

| Function | Lines | Purpose |
|---|---|---|
| `_force_sync_hard_stop` | L1183–1251 | Escalate sync failure to OpsGuard hard-stop + audit |
| `_active_failure_hard_stop_streak` | L1253–1260 | Configurable streak threshold |
| `_apply_controller_soft_pause` | L1263–1276 | Apply soft-pause to controller |
| `_apply_controller_resume` | L1279–1292 | Resume controller after recovery |
| `_apply_active_failure_policy` | L1295–1337 | Track failure streak, escalate |
| `_mark_active_failure_recovered` | L1340–1345 | Clear failure streak on success |
| `_active_sync_gate` | L1348–1385 | Check sync readiness, enforce timeout |
| `_fmt_contract_decimal` | L1388–1397 | Format Decimal for metadata |
| `_controller_accounting_contract_metadata` | L1400–1435 | Build accounting contract metadata dict |

### 7. Command Publishing

| Function | Lines | Purpose |
|---|---|---|
| `_publish_paper_exchange_command` | L1438–1592 | Main Redis command publisher (submit/cancel/sync) |
| `_ensure_sync_state_command` | L1595–1617 | Ensure sync_state command published at startup |

### 8. Event Consumption & Portfolio Sync

| Function | Lines | Purpose |
|---|---|---|
| `_sync_fill_to_portfolio` | L1619–1667 | Settle external fill into PaperDesk portfolio |
| `_consume_paper_exchange_events` | L1670–2021 | Main event stream consumer (~350 lines) |

### 9. Framework Patches & Bridge Installation

| Function | Lines | Purpose |
|---|---|---|
| `enable_framework_paper_compat_fallbacks` | L2034–2046 | Entry point for HB framework patches |
| `_patch_market_data_provider` | L2049–2066 | Patch MDP._create_non_trading_connector |
| `_patch_executor_base` | L2069–2144 | Patch ExecutorBase.get_trading_rules + get_in_flight_order |
| `install_paper_desk_bridge` | L2147–2232 | Full bridge installation (register instrument, budget checker, patches) |
| `_install_order_delegation` | L2235–2524 | Patch strategy.buy/sell/cancel for paper routing |
| `_patched_order` (inner) | L2265–2418 | Core order routing logic (shadow vs active) |
| `_patched_buy` (inner) | L2420–2424 | Buy delegation |
| `_patched_sell` (inner) | L2426–2430 | Sell delegation |
| `_patched_cancel` (inner) | L2432–2514 | Cancel delegation |
| `_hb_order_type_to_v2` | L2538–2545 | HB to PaperOrderType conversion |

### 10. Desk Tick Driver

| Function | Lines | Purpose |
|---|---|---|
| `drive_desk_tick` | L2548–2648 | Main tick entry point — parallel Redis I/O + desk.tick() + event fire |

---

## Proposed Target Modules

```
hbot/controllers/paper_engine_v2/
├── hb_bridge.py                    # SLIM: install_paper_desk_bridge, drive_desk_tick, enable_framework_paper_compat_fallbacks
├── bridge_state.py                 # BridgeState class, singleton, _LATENCY_TRACKER, _REDIS_IO_POOL
├── mode_resolver.py                # Mode resolution chain (_paper_exchange_mode_for_*, auto mode, heartbeat)
├── idempotency.py                  # Submit/cancel fingerprint, dedup, order ID generation
├── runtime_orders.py               # Runtime order store, upsert, prune, hydrate from snapshot
├── sync_gate.py                    # Sync handshake, failure policy, hard-stop escalation
├── command_publisher.py            # _publish_paper_exchange_command, _ensure_sync_state_command
├── event_consumer.py               # _consume_paper_exchange_events, _sync_fill_to_portfolio
├── framework_patches.py            # _patch_market_data_provider, _patch_executor_base
├── order_delegation.py             # _install_order_delegation, _patched_order/buy/sell/cancel
├── signal_consumer.py              # (already extracted)
├── adverse_inference.py            # (already extracted)
├── hb_event_fire.py                # (already extracted)
├── budget_checker.py               # (already extracted)
├── connector_patches.py            # (already extracted)
```

### Method-to-Module Mapping

| Target Module | Functions |
|---|---|
| `bridge_state.py` | `BridgeState`, `_bridge_state`, `_LATENCY_TRACKER`, `_REDIS_IO_POOL`, `_CANONICAL_CACHE`, `_get_signal_redis`, `_canonical_name` |
| `mode_resolver.py` | `_instance_env_suffix`, `_normalize_paper_exchange_mode`, `_parse_env_bool`, `_paper_exchange_service_only_for_instance`, `_paper_exchange_service_heartbeat_is_fresh`, `_paper_exchange_auto_mode`, `_paper_exchange_cursor_key`, `_bootstrap_paper_exchange_cursor`, `_paper_exchange_mode_for_instance`, `_resolve_controller_for_command`, `_paper_exchange_mode_for_route`, `_bridge_for_exchange_event` |
| `idempotency.py` | `_active_submit_retry_ttl_s`, `_active_submit_fingerprint`, `_active_submit_order_id`, `_active_cancel_retry_ttl_s`, `_active_cancel_fingerprint`, `_active_cancel_command_event_id`, `_active_cancel_all_retry_ttl_s`, `_active_cancel_all_fingerprint`, `_active_cancel_all_command_event_id` |
| `runtime_orders.py` | `_runtime_orders_store`, `_runtime_orders_bucket`, `_runtime_order_trade_type`, `_canonical_runtime_order_state`, `_runtime_order_state_flags`, `_upsert_runtime_order`, `_prune_runtime_orders`, `_paper_exchange_state_snapshot_path`, `_active_command_ttl_ms`, `_hydrate_runtime_orders_from_state_snapshot`, `_controller_tracked_order_ids`, `_cancel_reconciled_ghost_orders`, `_get_runtime_order_for_executor` |
| `sync_gate.py` | `_sync_handshake_key`, `_force_sync_hard_stop`, `_active_failure_hard_stop_streak`, `_apply_controller_soft_pause`, `_apply_controller_resume`, `_apply_active_failure_policy`, `_mark_active_failure_recovered`, `_active_sync_gate` |
| `command_publisher.py` | `_publish_paper_exchange_command`, `_ensure_sync_state_command`, `_fmt_contract_decimal`, `_controller_accounting_contract_metadata` |
| `event_consumer.py` | `_consume_paper_exchange_events`, `_sync_fill_to_portfolio` |
| `framework_patches.py` | `enable_framework_paper_compat_fallbacks`, `_patch_market_data_provider`, `_patch_executor_base` |
| `order_delegation.py` | `_install_order_delegation`, `_patched_order`, `_patched_buy`, `_patched_sell`, `_patched_cancel` |
| `hb_bridge.py` (slim) | `install_paper_desk_bridge`, `drive_desk_tick`, `_hb_order_type_to_v2`, utility functions at top, re-exports for backward compat |

---

## Shared State Between Modules

### BridgeState (Process-Wide Singleton)

All bridge modules share `_bridge_state`. The following state clusters exist:

| Cluster | Fields | Writers | Readers |
|---|---|---|---|
| Redis connection | `redis_client`, `redis_init_done` | bridge_state | all modules |
| Signal cursor | `last_signal_id` | signal_consumer | signal_consumer |
| Paper exchange cursor | `last_paper_exchange_event_id`, `paper_exchange_seen_event_ids`, `paper_exchange_cursor_initialized` | event_consumer | event_consumer |
| Sync handshake | `sync_state_published_keys`, `sync_confirmed_keys`, `sync_timeout_hard_stop_keys`, `sync_requested_at_ms_by_key` | sync_gate, event_consumer | sync_gate, command_publisher |
| Guard state | `prev_guard_states` | signal_consumer | signal_consumer |
| Mode cache | `paper_exchange_auto_mode_by_instance`, `paper_exchange_auto_mode_updated_ms_by_instance`, `paper_exchange_mode_warned_instances` | mode_resolver | mode_resolver |
| Failure tracking | `active_failure_streak_by_key` | sync_gate | sync_gate |
| Dedup caches | `active_submit_order_cache`, `active_cancel_command_cache`, `active_cancel_all_command_cache` | idempotency | idempotency |

### Strategy-Level State

The bridge attaches state to the HB `strategy` object:
- `strategy._paper_desk_v2_bridges` — bridge dict per connector
- `strategy._paper_exchange_runtime_orders` — runtime order tracking
- `strategy._paper_desk_v2_order_delegation_installed` — delegation flag

---

## Migration Phases (Safest First)

### Phase 1: `bridge_state.py` — Risk: **Very Low**

- Pure data class + singleton extraction
- No behavioral change — just move `BridgeState`, `_bridge_state`, `_CANONICAL_CACHE`
- All other modules import from here instead of module-level
- ~100 lines

### Phase 2: `mode_resolver.py` — Risk: **Low**

- 12 functions, ~280 lines
- Self-contained mode resolution logic
- Dependencies: `_bridge_state` (read-only for most), Redis (heartbeat check)
- No order/fill side effects

### Phase 3: `idempotency.py` — Risk: **Low**

- 9 functions, ~240 lines
- Pure fingerprint/cache logic
- Dependencies: `_bridge_state` caches, `_canonical_name`, mode resolver
- No external side effects beyond cache mutation

### Phase 4: `runtime_orders.py` — Risk: **Low-Medium**

- 13 functions, ~320 lines
- SimpleNamespace-based order tracking
- Dependencies: `_canonical_name`, snapshot file I/O
- Risk: `_upsert_runtime_order` is called from many places; must maintain exact API

### Phase 5: `sync_gate.py` — Risk: **Medium**

- 8 functions, ~220 lines
- Failure escalation affects controller state (hard-stop, soft-pause)
- Dependencies: mode resolver, bridge_state, controller OpsGuard
- Side effects: publishes audit events to Redis

### Phase 6: `command_publisher.py` — Risk: **Medium**

- 4 functions, ~200 lines
- `_publish_paper_exchange_command` is the critical command path
- Dependencies: mode resolver, sync gate, bridge_state, Redis
- Side effects: Redis XADD; failure triggers active failure policy

### Phase 7: `event_consumer.py` — Risk: **Medium-High**

- 2 functions, ~400 lines
- `_consume_paper_exchange_events` is the largest single function (~350 lines)
- Complex state machine: sync confirmation, fill routing, reject handling
- Dependencies: runtime_orders, sync_gate, mode_resolver, hb_event_fire
- Must be extracted after runtime_orders and sync_gate

### Phase 8: `framework_patches.py` — Risk: **Medium**

- 3 functions, ~120 lines
- Monkey-patches HB framework classes — fragile by nature
- Dependencies: `_canonical_name`, `_get_runtime_order_for_executor`
- Must preserve idempotent patch guards

### Phase 9: `order_delegation.py` — Risk: **High** (Extract Last)

- 5 functions, ~290 lines
- `_patched_order` is the core routing decision (shadow vs active)
- Monkey-patches `strategy.buy`/`sell`/`cancel` — the most sensitive path
- Dependencies: every other module (mode, sync, command, idempotency, runtime_orders)
- Must be extracted last when all dependencies have stable imports

---

## Risks

### Module-Level State
`_bridge_state` is a process-wide singleton. Extraction must ensure all modules reference the same instance. Using a `bridge_state.py` module with a module-level instance solves this naturally.

### Import Cycles
`hb_bridge.py` is the HB-boundary file. Several functions do lazy imports (`from hummingbot...`) inside function bodies to avoid circular imports. Extracted modules must preserve this pattern.

### Backward Compatibility
`hb_bridge.py` exports `install_paper_desk_bridge`, `drive_desk_tick`, `enable_framework_paper_compat_fallbacks`. The slim `hb_bridge.py` must re-export all public API from sub-modules to avoid breaking callers.

### Monkey-Patching Fragility
Framework patches (`_patch_executor_base`, `_install_order_delegation`) use `MethodType` binding and idempotent guards. These are inherently fragile across HB version upgrades. Extraction should not change the patching mechanism.

### Thread Safety
`_REDIS_IO_POOL` submits concurrent tasks in `drive_desk_tick`. Extracted modules called from pool threads must not hold shared locks or mutate bridge_state in non-thread-safe ways. Currently safe because each future targets isolated state.

### Event Consumer Complexity
`_consume_paper_exchange_events` (350 lines) handles sync confirmation, fill routing, reject escalation, and portfolio sync in a single function. It should eventually be decomposed internally, but the first extraction phase should move it as-is to `event_consumer.py`.
