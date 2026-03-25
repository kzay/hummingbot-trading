## ADDED Requirements

### Requirement: Stale-cancel queue accessed only via methods

Bot lanes and mixins SHALL NOT access `_pending_stale_cancel_actions` directly. The `SharedRuntimeKernel` SHALL expose two methods:
- `enqueue_stale_cancels(actions: list) -> None` — appends actions to the queue
- `replace_stale_cancels(actions: list) -> None` — replaces the entire queue (for regime side-change semantics)

All existing direct access sites SHALL be replaced:
- `quoting_mixin.py` (lines 139, 143): `self._pending_stale_cancel_actions.extend(...)` → `self.enqueue_stale_cancels(...)`
- `regime_mixin.py` (line 125): `self._pending_stale_cancel_actions = ...` → `self.replace_stale_cancels(...)`
- `pullback_v1.py` (lines 1620, 1626): `self._pending_stale_cancel_actions.extend(...)` → `self.enqueue_stale_cancels(...)`
- `ift_jota_v1.py` (lines 281, 295): `self._pending_stale_cancel_actions.extend(...)` → `self.enqueue_stale_cancels(...)`
- `cvd_divergence_v1.py` (lines 420, 427, 435): `self._pending_stale_cancel_actions.extend(...)` → `self.enqueue_stale_cancels(...)`

The `_pending_stale_cancel_actions` attribute remains on the instance for the adapter's `executors_to_refresh` to drain but is a private implementation detail.

#### Scenario: Bot lane enqueues stale cancels on side change
- **WHEN** `pullback_v1._resolve_quote_side_mode` detects a side change from `buy_only` to `off`
- **THEN** it SHALL call `self.enqueue_stale_cancels(self._cancel_active_quote_executors())` instead of `self._pending_stale_cancel_actions.extend(...)`
- **AND** the resulting `StopExecutorAction`s SHALL appear in the next `executors_to_refresh` return value

#### Scenario: Regime mixin replaces stale cancels on side-change
- **WHEN** `regime_mixin._apply_regime` detects `changed_one_sided is not None`
- **THEN** it SHALL call `self.replace_stale_cancels(self._cancel_stale_side_executors(...))` instead of direct assignment
- **AND** any previously enqueued cancels from earlier in the same tick SHALL be discarded (replace semantics)

#### Scenario: Existing behavior preserved
- **WHEN** a bot lane enqueues cancels via `enqueue_stale_cancels`
- **THEN** the executor adapter's `executors_to_refresh` SHALL drain them and include them in the returned actions, identically to the current direct-access behavior

### Requirement: Extra actions via `_strategy_extra_actions` hook

Bot lanes that need to inject additional `CreateExecutorAction`s SHALL override `_strategy_extra_actions() -> list` instead of overriding `determine_executor_actions` directly.

`SharedRuntimeKernel` SHALL define a default hook:
```python
def _strategy_extra_actions(self) -> list:
    return []
```

The `determine_executor_actions` override pattern SHALL be standardized as:
```python
def determine_executor_actions(self) -> list:
    actions = super().determine_executor_actions()
    actions.extend(self._strategy_extra_actions())
    return actions
```

Bot7 SHALL implement:
```python
def _strategy_extra_actions(self) -> list:
    actions = self._pb_pending_actions[:]
    self._pb_pending_actions.clear()
    return actions
```

#### Scenario: Bot7 trailing-stop actions injected via hook
- **WHEN** `pullback_v1.py` has trailing-stop `CreateExecutorAction`s in `_pb_pending_actions`
- **THEN** `_strategy_extra_actions` SHALL return and drain them
- **AND** `determine_executor_actions` SHALL include them after `super()`'s actions

#### Scenario: Bots without extra actions
- **WHEN** bot5 or bot6 do not override `_strategy_extra_actions`
- **THEN** the default empty list is returned and `determine_executor_actions` behavior is unchanged

### Requirement: Bot lanes SHALL NOT mutate `_runtime_levels` directly

No bot lane file under `hbot/controllers/bots/` SHALL contain assignments to `_runtime_levels.executor_refresh_time` or any other `_runtime_levels` attribute. The `executor_refresh_time` SHALL be set exclusively by the shared adapter's `build_execution_plan` from the regime-driven `refresh_s` value.

Bot7's `build_runtime_execution_plan` currently sets `self._runtime_levels.executor_refresh_time = int(data_context.regime_spec.refresh_s)` (line 1675). This line SHALL be removed. Bot7 SHALL call `super().build_runtime_execution_plan(execution_plan, data_context)` to let the adapter set regime-driven values, then extend with strategy-specific spreads/sizing only.

#### Scenario: Bot7 executor_refresh_time set by adapter
- **WHEN** bot7's `build_runtime_execution_plan` is called with regime `refresh_s: 30`
- **THEN** the adapter (via `super()`) SHALL set `_runtime_levels.executor_refresh_time = 30`
- **AND** bot7's override SHALL NOT set it again

#### Scenario: Neutral regime with top-level executor_refresh_time
- **WHEN** regime is `neutral` with no `refresh_s` override and top-level `executor_refresh_time: 120`
- **THEN** the adapter SHALL set `_runtime_levels.executor_refresh_time = 120`
- **AND** bot7 SHALL NOT override it

### Requirement: `_recently_issued_levels` cleared via method

Bot lanes SHALL NOT directly assign `self._recently_issued_levels = {}`. The `SharedRuntimeKernel` SHALL expose:
```python
def _reset_issued_levels(self) -> None:
    self._recently_issued_levels = {}
```

Bot7 (line 1593) SHALL call `self._reset_issued_levels()` instead of direct assignment.

#### Scenario: Bot7 clears issued levels after orphan sweep
- **WHEN** `pullback_v1._force_cancel_orphaned_orders` successfully cancels orphaned orders
- **THEN** it SHALL call `self._reset_issued_levels()` instead of `self._recently_issued_levels = {}`

### Requirement: Dynamic config fields SHALL be typed, not set via `__setattr__`

Bot lanes SHALL NOT use `object.__setattr__(self.config, ...)` to attach runtime-computed fields to the config object. Instead, the config class SHALL declare the field with a proper type annotation and `Field(default=None, exclude=True)`.

Bot7 SHALL add to `PullbackV1Config`:
```python
_pb_dynamic_tbc: Optional[TripleBarrierConfig] = Field(default=None, exclude=True)
```

Bot7 (lines 460, 464) SHALL replace `object.__setattr__(self.config, "_pb_dynamic_tbc", ...)` with `self.config._pb_dynamic_tbc = ...`.

#### Scenario: Dynamic TBC updated safely
- **WHEN** bot7 computes a dynamic `TripleBarrierConfig` during tick processing
- **THEN** it SHALL assign `self.config._pb_dynamic_tbc = dynamic_tbc` using the typed field
- **AND** the field SHALL NOT appear in `config.model_dump()` (excluded from serialization)

#### Scenario: Error path sets None
- **WHEN** the dynamic TBC computation fails
- **THEN** it SHALL assign `self.config._pb_dynamic_tbc = None` using the typed field

### Requirement: Architectural contract tests enforce boundary

`hbot/tests/architecture/test_bot_lane_boundary.py` SHALL contain contract tests that scan all Python files under `hbot/controllers/bots/` for forbidden patterns. These tests SHALL fail if any bot lane:

1. Contains `_runtime_levels.executor_refresh_time =` (or similar `_runtime_levels` attribute assignment)
2. Contains `._pending_stale_cancel_actions` (direct attribute access instead of method call)
3. Contains `object.__setattr__(self.config,` (dynamic config mutation)
4. Contains `_recently_issued_levels = {` (direct clearing instead of method call)

Tests SHALL follow the existing architecture test patterns in `hbot/tests/architecture/` (file scanning with regex, excluding comments and string literals where feasible).

#### Scenario: Contract test catches direct queue access
- **WHEN** a developer adds `self._pending_stale_cancel_actions.extend([...])` to a new bot lane
- **THEN** `test_bot_lanes_never_access_pending_stale_actions_directly` SHALL fail with a message identifying the file and line

#### Scenario: Existing architecture tests unaffected
- **WHEN** the boundary contract tests are added
- **THEN** all existing architecture tests in `hbot/tests/architecture/` SHALL continue to pass

#### Scenario: Shared infrastructure files NOT scanned
- **WHEN** `controller.py` or `quoting_mixin.py` accesses `_pending_stale_cancel_actions` directly (as the implementing module)
- **THEN** the contract tests SHALL NOT flag these — only files under `hbot/controllers/bots/` are scanned

### Requirement: No behavioral change from boundary formalization

All Phase 2 changes are refactors (rename, encapsulate, extract). No runtime behavior SHALL change:
- Executor lifecycle decisions remain identical
- Stale/stuck detection timing unchanged
- Fill/cancel event processing unchanged
- Spread, sizing, and quoting geometry unchanged
- Risk guards and kill switch behavior unchanged

#### Scenario: End-to-end behavior identical
- **WHEN** bot7 runs with the same config before and after Phase 2
- **THEN** the sequence of `CreateExecutorAction`s and `StopExecutorAction`s SHALL be identical for the same market data
