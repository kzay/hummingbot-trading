## MODIFIED Requirements

### Requirement: Entry timeout via shared adapter, not executor refresh override
Entry limit orders that are not filled SHALL be cancelled by the **shared runtime adapter** (`MarketMakingRuntimeAdapter.executors_to_refresh`) using the centralized `open_order_timeout_s` config field. The `pb_entry_timeout_s` config parameter SHALL be mapped to `open_order_timeout_s` at config initialization or in `build_runtime_execution_plan`. The effective external behavior is identical: an unfilled limit entry is cancelled after `pb_entry_timeout_s` seconds.

The bot lane SHALL NOT override `_runtime_levels.executor_refresh_time` with `pb_entry_timeout_s` or any entry timeout value. The `executor_refresh_time` SHALL remain at the regime-driven `refresh_s` value exclusively.

**Breaking change**: The `build_runtime_execution_plan` code block:
```python
if limit_entry and side != "off":
    entry_timeout = int(getattr(self.config, "pb_entry_timeout_s", 30))
    self._runtime_levels.executor_refresh_time = entry_timeout
```
SHALL be removed entirely. The equivalent functionality is provided by `open_order_timeout_s` in the shared adapter.

#### Scenario: Entry timeout behavior preserved
- **WHEN** bot7 config has `pb_entry_timeout_s: 30` and a limit buy order is placed at T=0
- **THEN** the shared adapter SHALL cancel the unfilled order after 30 seconds — externally identical to the previous mechanism

#### Scenario: executor_refresh_time tracks regime, not entry timeout
- **WHEN** regime transitions from `up` (`refresh_s: 30`) to `neutral` (`refresh_s` absent, top-level `executor_refresh_time: 120`)
- **THEN** `_runtime_levels.executor_refresh_time` SHALL change to 120, and `open_order_timeout_s` SHALL remain at 30 (from `pb_entry_timeout_s` mapping)

### Requirement: Bot lane declares intent, shared infra enforces
The `pullback_v1.py` strategy controller SHALL contain NO entry timeout bookkeeping logic, NO per-executor timers, and NO `StopExecutorAction` generation for entry timeout purposes. Its only timeout-related responsibility is mapping `pb_entry_timeout_s` to `open_order_timeout_s` on the config object.

#### Scenario: Code audit — no timeout in determine_executor_actions
- **WHEN** inspecting `pullback_v1.py`'s `determine_executor_actions`
- **THEN** it SHALL contain ONLY the base `super().determine_executor_actions()` call plus draining `_pb_pending_actions` (which contains only `CreateExecutorAction` objects, not stops)

### Requirement: `_resolve_quote_side_mode` stale cancellation unaffected
The `_resolve_quote_side_mode` method in `pullback_v1.py` extends `_pending_stale_cancel_actions` with `_cancel_stale_side_executors` and `_cancel_active_quote_executors` for side changes and mode transitions. This behavior SHALL remain unchanged — it is a quote-management concern, not an entry timeout concern.

### Requirement: `_force_cancel_orphaned_orders` unaffected
The `_force_cancel_orphaned_orders` method in `pullback_v1.py` cancels connector open orders not tied to active executors. This behavior SHALL remain unchanged.

### Requirement: `spread_engine.py` executor_refresh_time clamping unaffected
The `spread_engine.py` adjustments to `_runtime_levels.executor_refresh_time` (clamping for MM spread calculations) SHALL remain unaffected since the removal of the entry-timeout override only affects bot7's `build_runtime_execution_plan`, not the MM spread engine path.
