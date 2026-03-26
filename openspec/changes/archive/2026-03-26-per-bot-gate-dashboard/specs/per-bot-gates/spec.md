## ADDED Requirements

### Requirement: Telemetry payload includes strategy type and bot gate data
The telemetry mixin SHALL include `strategy_type` ("mm" or "directional") and a `bot_gates` object in every `bot_minute_snapshot` Redis stream payload. The `bot_gates` object SHALL contain the output of the active bot's `_bot*_gate_metrics()` method, keyed by bot prefix.

#### Scenario: MM bot publishes strategy type
- **WHEN** Bot1 (market-making) emits a minute snapshot
- **THEN** the payload contains `"strategy_type": "mm"` and `"bot_gates": {"bot1": {"state": "...", "reason": "...", "signal_side": "...", "signal_reason": "...", "signal_score": ...}}`

#### Scenario: Directional bot publishes strategy type and indicators
- **WHEN** Bot6 (directional CVD divergence) emits a minute snapshot
- **THEN** the payload contains `"strategy_type": "directional"` and `"bot_gates": {"bot6": {"state": "...", "reason": "...", ...}}` including strategy-specific fields like `cvd_divergence_ratio` and `adx`

#### Scenario: Bot gate metrics method missing
- **WHEN** a controller instance does not have a `_bot*_gate_metrics()` method
- **THEN** `bot_gates` SHALL be an empty dict and the payload SHALL still be published

### Requirement: Universal gates filtered by strategy type
The `_build_quote_gate_summary()` function SHALL accept a `strategy_type` parameter. When `strategy_type` is `"directional"`, the gates `edge`, `spread`, and `spread_cap` SHALL be omitted from the `quote_gates` array. When `strategy_type` is `"mm"` or not provided, all 8 gates SHALL be included.

#### Scenario: Directional bot omits MM-specific gates
- **WHEN** the API builds a gate summary for a directional bot instance
- **THEN** the `quote_gates` array SHALL NOT contain entries with keys `edge`, `spread`, or `spread_cap`
- **THEN** the `quote_gates` array SHALL contain `controller_state`, `risk_reasons`, `order_book`, `pnl_governor`, `orders`

#### Scenario: MM bot retains all gates
- **WHEN** the API builds a gate summary for an MM bot instance
- **THEN** the `quote_gates` array SHALL contain all 8 gates including `edge`, `spread`, and `spread_cap`

#### Scenario: No strategy type specified (backward compatibility)
- **WHEN** `strategy_type` is None or absent
- **THEN** all 8 universal gates SHALL be included (no filtering)

### Requirement: API response includes bot_gates array
The summary API response SHALL include a `bot_gates` array in the account section. Each entry SHALL contain `bot_id` (string), `strategy_type` (string), and `gates` (array of `{key, label, status, detail}` objects).

#### Scenario: Bot gates present in API response
- **WHEN** the latest telemetry payload contains `bot_gates` data
- **THEN** the API summary response SHALL include `bot_gates` with one entry per bot, each containing a `gates` array with strategy-specific gate entries

#### Scenario: No bot gates data available
- **WHEN** no telemetry payload has been received yet or `bot_gates` is empty
- **THEN** the API summary response SHALL include `bot_gates` as an empty array

### Requirement: Per-bot gate status derivation
Each bot's gate fields SHALL be converted to gate entries with computed status values. The mapping SHALL be:
- `gate_state == "blocked"` → `status: "fail"`
- `gate_state == "active"` → `status: "pass"`
- `gate_state == "idle"` → `status: "warn"`
- Signal score and indicator fields → `status: "info"` (informational only)

#### Scenario: Bot6 blocked gate renders as fail
- **WHEN** Bot6 telemetry reports `gate_state: "blocked"` with `reason: "trade_features_warmup"`
- **THEN** the bot_gates entry for bot6 SHALL have a gate with `key: "gate_state"`, `status: "fail"`, `detail: "trade_features_warmup"`

#### Scenario: Bot7 active gate renders as pass with indicators
- **WHEN** Bot7 telemetry reports `gate_state: "active"` with `adx: 28.5` and `rsi: 55.2`
- **THEN** the bot_gates entry for bot7 SHALL include gates: `gate_state` (status "pass"), `adx` (status "info", detail "28.5"), `rsi` (status "info", detail "55.2")

### Requirement: Frontend renders per-bot gate sections
The `BotGateBoardPanel` component SHALL render bot-specific gate sections below the universal gates table when `bot_gates` data is available. Each bot section SHALL display the bot ID, strategy type badge, and a gate table using the same row format as universal gates.

#### Scenario: Dashboard shows bot-specific gates
- **WHEN** the API response contains `bot_gates` with entries for bot1 and bot6
- **THEN** the panel SHALL render a "Bot1 (mm)" section with bot1's gates and a "Bot6 (directional)" section with bot6's gates below the universal gates

#### Scenario: No bot gates data renders gracefully
- **WHEN** `bot_gates` is empty or undefined
- **THEN** no bot-specific sections SHALL be rendered; only universal gates are shown

#### Scenario: Bot sections are collapsible
- **WHEN** a bot gate section is rendered
- **THEN** it SHALL be collapsible (click to expand/collapse) with collapsed as the default state

### Requirement: TypeScript types updated for bot gates
The `SummaryAccount` interface SHALL include an optional `bot_gates` field typed as an array of `BotGateGroup` objects, where each `BotGateGroup` has `bot_id: string`, `strategy_type: string`, and `gates: QuoteGate[]`.

#### Scenario: Type safety for bot gates
- **WHEN** a developer accesses `state.summaryAccount.bot_gates`
- **THEN** TypeScript SHALL provide type-safe access to `bot_id`, `strategy_type`, and `gates` array with `{key, label, status, detail}` elements
