# shared_mm_v24.py Decomposition Plan

## Current State

| Metric | Value |
|---|---|
| File | `hbot/controllers/shared_mm_v24.py` |
| Total lines | ~4,104 |
| Classes | `EppV24Config` (L172–881), `SharedRuntimeKernel` (L883–4072), `EppV24Controller` (L4076–4085), `SharedMmV24Config` (L4087–4091), `SharedMmV24Controller` (L4093–4095) |
| Mixins used | `FillHandlerMixin`, `RiskMixin`, `TelemetryMixin`, `AutoCalibrationMixin`, `PositionMixin` |
| Init state vars | ~250 instance variables set in `__init__` (L1002–1343) |
| Module-level helpers | 8 functions (L89–170) |
| Config fields | ~200 Pydantic fields in `EppV24Config` (L172–881) |

### Existing Extractions (Already Done)

The following responsibilities have already been extracted to mixins:
- **FillHandlerMixin** — `did_fill_order`, `did_cancel_order`, position update from fills, fill deduplication
- **RiskMixin** — `_evaluate_all_risk`, `_resolve_guard_state`, derisk force mode, PnL governor size mult, slippage/edge guards
- **TelemetryMixin** — `_emit_tick_output`, `_publish_bot_minute_snapshot_telemetry`, `to_format_status`, tick snapshot building
- **AutoCalibrationMixin** — minute/fill recording, auto-calibration run logic, report writing
- **PositionMixin** — `check_position_rebalance`, position reconciliation, startup sync, recovery guard

---

## Method Inventory by Responsibility Group

### 1. Tick Orchestration (Core Loop)

| Method | Lines | Access |
|---|---|---|
| `update_processed_data` | L1344–1445 | public (async) |
| `_preflight_hot_path` | L1448–1461 | private |
| `_check_recovery_guard` | L1462–1506 | private |
| `_cleanup_recovery_zombie_executors` | L1507–1547 | private |
| `_run_supervisory_maintenance` | L1547–1555 | private |
| `_ensure_price_sampler_started` | L1580–1596 | private |
| `_run_price_sample_loop` | L1597–1619 | private (async) |
| `_maybe_seed_price_buffer` | L1619–1686 | private |
| `_expire_external_intent_overrides` | L1686–1728 | private |
| `_intent_expires_ts` | L1728–1740 | static |

### 2. Regime Detection & Spread/Edge Computation

| Method | Lines | Access |
|---|---|---|
| `_resolve_regime_and_targets` | L1749–1764 | private |
| `_update_edge_gate_ewma` | L1766–1788 | private |
| `_detect_regime` | L2362–2404 | private |
| `_get_ohlcv_ema_and_atr` | L2309–2360 | private |
| `_compute_spread_and_edge` | L3380–3429 | private |
| `_update_adaptive_history` | L3431–3452 | private |
| `_compute_adaptive_spread_knobs` | L3454–3669 | private |
| `_evaluate_market_conditions` | L3671–3732 | private |
| `_order_book_stale_age_s` | L3734–3737 | private |
| `_is_order_book_stale` | L3739–3748 | private |
| `_get_top_of_book` | L3750–3752 | private |
| `_compute_ob_imbalance` | L3754–3762 | private |
| `_pick_spread_pct` | L2556–2559 | private |
| `_pick_levels` | L2561–2562 | private |
| `_build_side_spreads` | L2564–2567 | private |

### 3. Execution Plan & Level Management

| Method | Lines | Access |
|---|---|---|
| `_compute_levels_and_sizing` | L1790–1810 | private |
| `build_runtime_execution_plan` | L1812–1814 | public |
| `_apply_runtime_execution_plan` | L1816–1822 | private |
| `_make_runtime_family_adapter` | L1824–1825 | private |
| `_apply_runtime_spreads_and_sizing` | L2569–2598 | private |
| `get_levels_to_execute` | L2804–2858 | public |
| `executors_to_refresh` | L2860–2861 | public |
| `_in_reconnect_refresh_suppression_window` | L2863–2872 | private |
| `get_not_active_levels_ids` | L2874–2885 | public |
| `get_price_and_amount` | L2887–2888 | public |
| `_runtime_spreads_and_amounts_in_quote` | L2890–2891 | private |
| `_runtime_required_base_amount` | L2893–2894 | private |
| `_perp_target_base_amount` | L2896–2905 | private |
| `get_executor_config` | L2198–2200 | public |

### 4. Alpha Policy & Selective Quoting

| Method | Lines | Access |
|---|---|---|
| `_resolve_quote_side_mode` | L1827–1909 | private |
| `_apply_spread_competitiveness_cap` | L1910–1928 | private |
| `_compute_selective_quote_quality` | L1929–2033 | private |
| `_compute_alpha_policy` | L2034–2165 | private |
| `_extend_processed_data_before_log` | L2166–2178 | private |
| `extend_runtime_processed_data` | L2179–2197 | public |

### 5. Order Management

| Method | Lines | Access |
|---|---|---|
| `_cancel_stale_side_executors` | L2406–2430 | private |
| `_cancel_active_quote_executors` | L2432–2471 | private |
| `_cancel_alpha_no_trade_orders` | L2473–2504 | private |
| `_cancel_active_runtime_orders` | L2505–2555 | private |
| `_open_order_level_ids` | L2603–2644 | private |
| `_open_order_count` | L2646–2665 | private |
| `_cancel_orphan_orders_on_startup` | L2667–2743 | private |
| `_cancel_stale_orders` | L2745–2800 | private |

### 6. External Intent / Soft-Pause API

| Method | Lines | Access |
|---|---|---|
| `set_external_soft_pause` | L2201–2208 | public |
| `apply_execution_intent` | L2209–2295 | public |

### 7. Connector / Balance / Quantization

| Method | Lines | Access |
|---|---|---|
| `_connector` | L2600–2601 | private |
| `_trading_rule` | L2801–2802 | private |
| `_get_mid_price` | L3129–3130 | private |
| `_get_price_for_buffer` | L3132–3141 | private |
| `_get_balances` | L3143–3144 | private |
| `_compute_equity_and_base_pcts` | L3146–3184 | private |
| `_refresh_margin_ratio` | L3186–3217 | private |
| `_connector_ready` | L3219–3220 | private |
| `_balances_consistent` | L3222–3223 | private |
| `_compute_total_base_with_locked` | L3225–3252 | private |
| `_quantize_price` | L2907–2921 | private |
| `_quantize_amount` | L2923–2949 | private |
| `_quantize_amount_up` | L2951–2977 | private |
| `_min_notional_quote` | L3259–3267 | private |
| `_order_size_constraints` | L3269–3293 | private |
| `_min_base_amount` | L3295–3308 | private |
| `_project_total_amount_quote` | L3310–3337 | private |
| `_cancel_per_min` | L3254–3257 | private |
| `_get_kelly_order_quote` | L2296–2307 | private |

### 8. Fee / Funding / Risk Periphery

| Method | Lines | Access |
|---|---|---|
| `_ensure_fee_config` | L2979–3054 | private |
| `_refresh_funding_rate` | L3056–3081 | private |
| `_check_portfolio_risk_guard` | L3083–3128 | private |
| `_risk_loss_metrics` | L3337–3355 | private |
| `_risk_policy_checks` | L3356–3369 | private |
| `_edge_gate_update` | L3370–3378 | private |

### 9. State Management / Daily Lifecycle

| Method | Lines | Access |
|---|---|---|
| `_track_daily_equity` | L1740–1748 | private |
| `_maybe_roll_day` | L3765–3831 | private |
| `_daily_state_path` | L3833–3841 | private |
| `_fills_csv_path` | L3843–3856 | private |
| `_hydrate_seen_fill_order_ids_from_csv` | L3858–3940 | private |
| `_load_daily_state` | L3942–4000 | private |
| `_maybe_reconcile_desk_state` | L4004–4048 | private |
| `_save_daily_state` | L4050–4071 | private |

### 10. History Provider

| Method | Lines | Access |
|---|---|---|
| `_history_provider_enabled` | L1555–1557 | private |
| `_history_seed_enabled` | L1558–1560 | private |
| `_get_history_provider` | L1561–1565 | private |
| `_required_seed_bars` | L1566–1576 | private |
| `_history_seed_policy` | L1577–1579 | private |

---

## Proposed Target Modules

### Module Map

```
hbot/controllers/
├── shared_mm_v24.py              # SLIM: config, class shell, __init__, public API surface only
├── kernel/
│   ├── __init__.py
│   ├── tick_orchestrator.py       # Tick loop, preflight, supervisory maintenance
│   ├── regime_spread_engine.py    # Regime detection, spread/edge, adaptive knobs, market conditions
│   ├── level_engine.py            # Execution plan building, level selection, sizing, quantization
│   ├── order_lifecycle.py         # Order cancel/refresh, orphan cleanup, stale management
│   ├── alpha_policy.py            # Quote side mode, selective quoting, alpha policy
│   ├── fee_funding.py             # Fee resolution, funding rate, portfolio risk guard
│   ├── daily_state.py             # Day roll, daily equity tracking, state load/save, CSV hydration
│   ├── connector_helpers.py       # Balance/equity, mid price, margin ratio, connector wrappers
│   └── external_intent.py         # Soft-pause API, execution intent, intent expiry
```

### Method-to-Module Mapping

| Target Module | Methods |
|---|---|
| `tick_orchestrator.py` | `update_processed_data`, `_preflight_hot_path`, `_check_recovery_guard`, `_cleanup_recovery_zombie_executors`, `_run_supervisory_maintenance`, `_ensure_price_sampler_started`, `_run_price_sample_loop`, `_maybe_seed_price_buffer`, `_history_*` helpers |
| `regime_spread_engine.py` | `_resolve_regime_and_targets`, `_update_edge_gate_ewma`, `_detect_regime`, `_get_ohlcv_ema_and_atr`, `_compute_spread_and_edge`, `_update_adaptive_history`, `_compute_adaptive_spread_knobs`, `_evaluate_market_conditions`, `_order_book_stale_age_s`, `_is_order_book_stale`, `_get_top_of_book`, `_compute_ob_imbalance`, `_pick_spread_pct`, `_pick_levels`, `_build_side_spreads` |
| `level_engine.py` | `_compute_levels_and_sizing`, `build_runtime_execution_plan`, `_apply_runtime_execution_plan`, `_apply_runtime_spreads_and_sizing`, `get_levels_to_execute`, `executors_to_refresh`, `get_not_active_levels_ids`, `get_price_and_amount`, `_runtime_*` helpers, quantize methods |
| `order_lifecycle.py` | `_cancel_stale_side_executors`, `_cancel_active_quote_executors`, `_cancel_alpha_no_trade_orders`, `_cancel_active_runtime_orders`, `_open_order_level_ids`, `_open_order_count`, `_cancel_orphan_orders_on_startup`, `_cancel_stale_orders`, `_in_reconnect_refresh_suppression_window` |
| `alpha_policy.py` | `_resolve_quote_side_mode`, `_apply_spread_competitiveness_cap`, `_compute_selective_quote_quality`, `_compute_alpha_policy`, `_extend_processed_data_before_log`, `extend_runtime_processed_data` |
| `fee_funding.py` | `_ensure_fee_config`, `_refresh_funding_rate`, `_check_portfolio_risk_guard`, `_risk_loss_metrics`, `_risk_policy_checks`, `_edge_gate_update`, `_get_kelly_order_quote` |
| `daily_state.py` | `_track_daily_equity`, `_maybe_roll_day`, `_daily_state_path`, `_fills_csv_path`, `_hydrate_seen_fill_order_ids_from_csv`, `_load_daily_state`, `_maybe_reconcile_desk_state`, `_save_daily_state` |
| `connector_helpers.py` | `_connector`, `_trading_rule`, `_get_mid_price`, `_get_price_for_buffer`, `_get_balances`, `_compute_equity_and_base_pcts`, `_refresh_margin_ratio`, `_connector_ready`, `_balances_consistent`, `_compute_total_base_with_locked`, `_min_notional_quote`, `_order_size_constraints`, `_min_base_amount`, `_project_total_amount_quote`, `_cancel_per_min` |
| `external_intent.py` | `set_external_soft_pause`, `apply_execution_intent`, `_expire_external_intent_overrides`, `_intent_expires_ts` |

---

## Shared State Between Modules

The `SharedRuntimeKernel.__init__` sets ~250 instance variables. These form the shared state contract between extracted modules. Key state clusters:

### State that most modules read

- `self.config` — immutable after init
- `self._is_perp` — immutable after init
- `self.processed_data` — written by telemetry, read by many
- `self._ops_guard` — state machine, read/written by risk + tick orchestrator

### State clusters by module

| State Cluster | Primary Writer | Readers |
|---|---|---|
| `_price_buffer`, `_regime_ema_value` | regime_spread_engine | tick_orchestrator, alpha_policy |
| `_active_regime`, `_pending_regime`, `_regime_hold_counter` | regime_spread_engine | alpha_policy, telemetry |
| `_runtime_levels` (spreads, amounts, refresh_time) | level_engine | order_lifecycle, tick_orchestrator |
| `_daily_equity_open`, `_daily_equity_peak`, `_traded_notional_today` | daily_state | fee_funding, regime_spread_engine |
| `_position_base`, `_avg_entry_price`, `_position_gross_base` | FillHandlerMixin + PositionMixin | connector_helpers, risk, level_engine |
| `_maker_fee_pct`, `_taker_fee_pct`, `_fee_resolved` | fee_funding | regime_spread_engine |
| `_edge_gate_blocked`, `_soft_pause_edge`, `_net_edge_gate` | fee_funding/regime | tick_orchestrator, alpha_policy |
| `_fill_edge_ewma`, `_adverse_fill_count`, `_last_fill_ts` | FillHandlerMixin | regime_spread_engine, alpha_policy |
| `_alpha_policy_state`, `_selective_quote_state` | alpha_policy | level_engine, order_lifecycle |
| `_external_soft_pause`, `_external_target_base_pct_override` | external_intent | tick_orchestrator, regime |
| `_recently_issued_levels` | level_engine | order_lifecycle |

### Proposed State Access Pattern

All extracted modules will operate as **method collections** that still live on `self` (the controller instance). The extraction pattern is:

1. Move methods into module files as standalone functions or mixin classes.
2. Each function receives `self` (the controller) as first parameter.
3. State remains on `self` — no new data-transfer objects in Phase 1.
4. Later phases may introduce a `KernelState` dataclass to formalize the contract.

---

## Migration Phases (Safest First)

### Phase 1: `external_intent.py` — Risk: **Very Low**

- 4 methods, ~140 lines
- No complex state dependencies — reads/writes `_external_*` variables
- No coupling to regime, spread, or order management
- Test impact: isolated, easy to unit-test in extraction

### Phase 2: `daily_state.py` — Risk: **Low**

- 8 methods, ~300 lines
- Self-contained day-roll, state persistence, CSV hydration
- Dependencies: `_get_mid_price`, `_compute_equity_and_base_pcts` (can call via `self`)
- Test impact: daily roll logic already covered in existing tests

### Phase 3: `connector_helpers.py` — Risk: **Low**

- 15 methods, ~300 lines
- Pure delegation wrappers around `_runtime_adapter`
- No complex logic — mostly getattr chains and quantization math
- Test impact: many methods are thin wrappers, test surface is small

### Phase 4: `fee_funding.py` — Risk: **Low-Medium**

- 7 methods, ~200 lines
- `_ensure_fee_config` has multi-branch resolution logic but is self-contained
- Writes `_maker_fee_pct`, `_taker_fee_pct` which are read by spread engine
- Test impact: fee resolution is well-tested; funding is simple

### Phase 5: `order_lifecycle.py` — Risk: **Medium**

- 9 methods, ~400 lines
- Heavy interaction with executor framework (`executors_info`, `filter_executors`)
- Imports HB `StopExecutorAction`; needs framework stubs in tests
- Dependencies: `_runtime_levels`, connector, `_recently_issued_levels`
- Test impact: order cancel paths affect correctness; thorough testing needed

### Phase 6: `alpha_policy.py` — Risk: **Medium**

- 6 methods, ~350 lines
- `_compute_alpha_policy` is complex (~130 lines) with many state writes
- `_compute_selective_quote_quality` interacts with fill history
- Dependencies: regime state, spread state, market conditions
- Test impact: alpha policy changes affect quoting behavior directly

### Phase 7: `regime_spread_engine.py` — Risk: **Medium-High**

- 15 methods, ~700 lines
- Core pricing logic — errors here cause mispricing
- `_compute_adaptive_spread_knobs` is 220 lines with daily PnL governor
- Heavy reads from fill/fee/position state
- Test impact: regime transitions and spread calculation are critical paths

### Phase 8: `level_engine.py` — Risk: **Medium-High**

- 14 methods, ~350 lines
- `get_levels_to_execute` is the order placement decision point
- Interacts with `_runtime_family_adapter` and executor framework
- Dependencies: regime, spread, order lifecycle, quantization
- Test impact: level selection errors cause missing/duplicate orders

### Phase 9: `tick_orchestrator.py` — Risk: **High** (Extract Last)

- 10 methods, ~350 lines
- `update_processed_data` is the coordination nexus — calls everything else
- Must be extracted last after all callees have stable interfaces
- Recovery guard and zombie executor cleanup have side effects
- Test impact: integration-level; the main tick test must pass identically

---

## Risks

### Cross-cutting State Mutation
The `SharedRuntimeKernel` has ~250 instance variables set in `__init__`. Many methods read/write overlapping subsets. Extraction must preserve mutation ordering within a tick.

### HB Framework Coupling
Several methods import from `hummingbot.strategy_v2` at call time. These imports must remain lazy to avoid circular dependencies. Extracted modules must not add new top-level HB imports.

### Mixin Interaction
Five existing mixins already split behavior across files. Adding a `kernel/` package creates a second axis of decomposition. Methods that call mixin methods (e.g., `_evaluate_all_risk` in RiskMixin called from `update_processed_data`) must still resolve through `self`.

### Test Coverage
The current test suite tests `SharedRuntimeKernel` as a monolith. Each extraction phase must verify that existing tests pass without modification before adding unit tests for the extracted module.

### Performance
The tick loop is latency-sensitive (~50ms target). Method extraction must not add Python function-call overhead via deep indirection chains. Prefer flat delegation over decorator patterns.

### Config Class Size
`EppV24Config` is 700+ lines. It should eventually be split into config groups (regime, spread, risk, alpha, adaptive), but this is a separate task from the kernel decomposition.
