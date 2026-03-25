## ADDED Requirements

### Requirement: Shared adapter manages entry timeout via `open_order_timeout_s`
The shared runtime adapter (`MarketMakingRuntimeAdapter.executors_to_refresh`) SHALL manage limit entry timeouts when `open_order_timeout_s > 0` in the controller's config. For each active executor that is acknowledged (non-empty `order_id` via `getattr(executor, "order_id", "")`), not yet trading (`is_trading=False`), and whose age exceeds `open_order_timeout_s`, the adapter SHALL emit a `StopExecutorAction`.

#### Scenario: Limit entry times out at 30s (centralized)
- **WHEN** a limit buy executor is created at T=0, the controller's `open_order_timeout_s=30`, the order is acknowledged (`order_id` is set via `BuyOrderCreatedEvent`), and no fill occurs
- **THEN** on the first `executors_to_refresh` call after T=30, the shared adapter SHALL include a `StopExecutorAction` for that executor in its return list

#### Scenario: Limit entry fills within timeout
- **WHEN** a limit buy executor is created at T=0 with `open_order_timeout_s=30` and the order fills at T=15
- **THEN** `is_trading` becomes `True`, and the adapter SHALL NOT emit a `StopExecutorAction` for entry timeout

#### Scenario: open_order_timeout_s disabled (default)
- **WHEN** `open_order_timeout_s=0` (default value)
- **THEN** the entry timeout logic in `executors_to_refresh` SHALL be inert — no additional `StopExecutorAction`s are emitted beyond the existing stale/stuck logic

#### Scenario: Market order executor not subject to entry timeout
- **WHEN** an executor places a market order (fills immediately, `is_trading=True`)
- **THEN** the entry timeout logic SHALL NOT apply

#### Scenario: Unacknowledged executor not subject to entry timeout
- **WHEN** an executor has no `order_id` (paper bridge hasn't fired acceptance event yet) and `open_order_timeout_s > 0`
- **THEN** the entry timeout logic SHALL NOT apply to this executor; it falls through to the existing `_is_unacked_executor` stuck detection path

### Requirement: Entry timeout respects reconnect suppression
When `_in_reconnect_refresh_suppression_window` returns `True`, the entry timeout logic SHALL be suppressed alongside the existing stale/stuck logic. Entry-timed-out executors SHALL NOT be stopped during reconnect.

#### Scenario: Reconnect suppression active
- **WHEN** `_in_reconnect_refresh_suppression_window` returns `True` and an acknowledged executor has age > `open_order_timeout_s`
- **THEN** the adapter SHALL NOT emit a `StopExecutorAction` for entry timeout

### Requirement: `order_id` access via `getattr` (duck-typing safety)
All entry-timeout filters SHALL access `executor.order_id` via `getattr(executor, "order_id", "")` to handle duck-typed `ExecutorInfo` objects that may not have the attribute. Direct attribute access (`executor.order_id`) SHALL NOT be used in filter lambdas.

### Requirement: Action deduplication by `executor_id`
The final `actions` list returned by `executors_to_refresh` SHALL be deduplicated by `executor_id` before returning. An executor that appears in both `entry_timed_out` and `stale_executors` (if past both thresholds) or in `_pending_stale_cancel_actions` SHALL only produce one `StopExecutorAction`.

#### Scenario: Executor past both entry timeout and stale threshold
- **GIVEN** `open_order_timeout_s=30`, `stale_age_s=30`, grace window = 60s
- **WHEN** an acknowledged executor has age = 65s (past entry timeout AND past grace window)
- **THEN** the actions list SHALL contain exactly ONE `StopExecutorAction` for that executor, not two

### Requirement: Shared config field `open_order_timeout_s`
`DirectionalRuntimeConfig` SHALL include a field `open_order_timeout_s: int` with default `0` (disabled). Bot lanes that use limit entries configure this value to control how long unfilled limit orders survive. The field MAY also be added to `EppV24Config` for MM bots that need it in the future.

#### Scenario: Bot7 configures via `pb_entry_timeout_s` mapping
- **WHEN** bot7's config has `pb_entry_timeout_s: 30`
- **THEN** the bot7 config class or `build_runtime_execution_plan` SHALL set `open_order_timeout_s = pb_entry_timeout_s` so the shared adapter picks it up
- **AND** this SHALL be the only per-lane logic needed — no custom timeout bookkeeping

#### Scenario: Bot5/Bot6 unaffected
- **WHEN** bot5 or bot6 do not set `open_order_timeout_s` in their config
- **THEN** `open_order_timeout_s` SHALL default to `0` and the entry timeout logic is inert

#### Scenario: Future bot uses limit entries
- **WHEN** a new directional bot sets `open_order_timeout_s: 45` in its YAML config
- **THEN** the shared adapter SHALL manage 45s entry timeout with zero additional per-lane code

### Requirement: `executor_refresh_time` not overridden by entry timeout
No bot lane SHALL write an entry timeout value into `_runtime_levels.executor_refresh_time`. The `executor_refresh_time` SHALL be set exclusively by the regime-driven `refresh_s` value (from `regime_specs_override` or top-level config) in the shared adapter's `build_execution_plan` or the bot's `build_runtime_execution_plan`.

#### Scenario: Regime refresh_s controls executor_refresh_time
- **WHEN** regime is "up" with `refresh_s: 30` and `pb_entry_timeout_s: 30`
- **THEN** `_runtime_levels.executor_refresh_time` SHALL be 30 (from regime, not from entry timeout)

#### Scenario: Neutral regime with top-level executor_refresh_time
- **WHEN** regime is "neutral" with no `refresh_s` override and top-level `executor_refresh_time: 120`
- **THEN** `_runtime_levels.executor_refresh_time` SHALL be 120

### Requirement: Stale-executor filter respects acknowledged orders with entry timeout
In `executors_to_refresh`, when `open_order_timeout_s > 0`, an acknowledged executor (non-empty `order_id` via `getattr`) SHALL NOT be flagged stale while `now - executor.timestamp <= max(open_order_timeout_s, stale_age_s) + grace_s`, where `grace_s` defaults to `stale_age_s`. This ensures the entry timeout fires before the stale sweep catches acknowledged limit entries.

When `open_order_timeout_s == 0`, this guard is inert and existing stale behavior is unchanged.

#### Scenario: Acknowledged limit order within entry timeout + grace
- **GIVEN** `stale_age_s=30`, `open_order_timeout_s=30`, so grace window = `max(30,30) + 30 = 60s`
- **WHEN** an executor has `order_id=pe-abc123`, `is_trading=False`, and `age=45s`
- **THEN** the executor SHALL NOT be flagged stale (45 < 60)

#### Scenario: Acknowledged limit order exceeds grace window
- **GIVEN** `stale_age_s=30`, `open_order_timeout_s=30`, grace window = 60s
- **WHEN** an executor has `order_id=pe-abc123`, `is_trading=False`, and `age=65s`
- **THEN** the executor SHALL be flagged stale (65 > 60) — safety net catches it

#### Scenario: open_order_timeout_s=0 preserves existing behavior
- **GIVEN** `stale_age_s=30`, `open_order_timeout_s=0`
- **WHEN** an executor has `order_id=pe-abc123`, `is_trading=False`, and `age=35s`
- **THEN** the executor SHALL be flagged stale (existing behavior, guard is inert)

#### Scenario: Unacknowledged executor beyond ack timeout
- **WHEN** `ack_timeout_s=5`, an executor has no `order_id`, `is_trading=False`, and `age=8s`
- **THEN** the executor SHALL be flagged stuck (existing behavior, unchanged)

#### Scenario: Trading executor never flagged stale
- **WHEN** any executor has `is_trading=True`
- **THEN** it SHALL NOT be flagged stale regardless of age

### Requirement: No behavioral change for bots without limit entries
Bots that use market orders exclusively (e.g., bot1) or do not set `open_order_timeout_s` (e.g., bot5, bot6) SHALL experience zero behavioral change from these modifications.

#### Scenario: Bot1 market order lifecycle
- **WHEN** bot1 creates an executor with `open_order_type=MARKET` and `open_order_timeout_s=0`
- **THEN** the order fills immediately, `is_trading=True`, and no entry timeout or stale-filter guard affects the executor

### Requirement: `_cancel_stale_orders` respects centralized timeout
The `_cancel_stale_orders` method in `supervisory_mixin.py` operates on connector-level open orders (via `connector.get_open_orders()`), using the ORDER's `creation_timestamp` for age calculation. When `open_order_timeout_s > 0`, open orders with `created_ts > 0` SHALL NOT be cancelled while `(now - created_ts) < max(open_order_timeout_s, stale_age_s) + stale_age_s`. Orders with `created_ts <= 0` are already skipped by existing logic and remain unaffected.

### Requirement: Fallback safety when D1 fails
If the paper bridge fails to fire acceptance events (D1 not working), executors remain unacknowledged (`order_id` empty). In this case, the entry timeout logic SHALL NOT apply (it requires non-empty `order_id`), and executors SHALL fall through to the existing `_is_unacked_executor` stuck detection → `_consecutive_stuck_ticks` escalation → `SOFT_PAUSE` via `risk_mixin.py`. This is the intended fallback behavior and SHALL NOT be suppressed.
