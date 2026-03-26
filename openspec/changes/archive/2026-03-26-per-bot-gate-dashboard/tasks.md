## 1. Telemetry Pipeline Extension

- [x] 1.1 Add `strategy_type` property to controller base classes: `StrategyRuntimeV24Config` returns `"mm"`, `DirectionalStrategyRuntimeV24Config` returns `"directional"`
- [x] 1.2 In `telemetry_mixin.py`, add `strategy_type` field to the minute snapshot payload from `self.config.strategy_type`
- [x] 1.3 In `telemetry_mixin.py`, add `bot_gates` dict to payload by calling `_bot*_gate_metrics()` via `getattr` with fallback to empty dict
- [x] 1.4 Include key strategy-specific indicator fields from `processed_data` in the `bot_gates` dict (bot6: cvd_divergence_ratio, adx, hedge_state; bot7: adx, rsi)

## 2. API Backend — Strategy-Aware Gate Filtering

- [x] 2.1 Add `strategy_type: Optional[str] = None` parameter to `_build_quote_gate_summary()` in `_helpers.py`
- [x] 2.2 When `strategy_type == "directional"`, omit gates with keys `edge`, `spread`, `spread_cap` from the `quote_gates` list
- [x] 2.3 Pass `strategy_type` from the stored telemetry payload through to `_build_quote_gate_summary()` in the API summary builder

## 3. API Backend — Bot Gates Response

- [x] 3.1 Add `_build_bot_gates()` function in `_helpers.py` that converts raw `bot_gates` telemetry dict into the structured `[{bot_id, strategy_type, gates: [{key, label, status, detail}]}]` array
- [x] 3.2 Implement per-bot gate status derivation: gate_state → fail/pass/warn, signal/indicator fields → info
- [x] 3.3 Define gate label mappings per bot (bot1: 3 gates, bot5: 4 gates, bot6: 6 gates, bot7: 4 gates)
- [x] 3.4 Include `bot_gates` array in the account summary section of the API response

## 4. Frontend Types and Store

- [x] 4.1 Add `BotGateGroup` interface to `realtime.ts`: `{bot_id: string, strategy_type: string, gates: QuoteGate[]}`
- [x] 4.2 Add `bot_gates?: BotGateGroup[]` to `SummaryAccount` interface
- [x] 4.3 Add `gateTone` mappings for new status values if needed in `presentation.ts`

## 5. Frontend — BotGateBoardPanel Enhancement

- [x] 5.1 Read `bot_gates` from `useDashboardStore` state in `BotGateBoardPanel.tsx`
- [x] 5.2 Render collapsible per-bot sections below the universal gates table, each showing bot_id, strategy_type badge, and gate rows
- [x] 5.3 Default bot sections to collapsed state with click-to-expand behavior
- [x] 5.4 Handle empty/missing `bot_gates` gracefully (render nothing)

## 6. Testing and Verification

- [x] 6.1 Add unit test for `_build_quote_gate_summary()` with `strategy_type="directional"` verifying edge/spread/spread_cap are omitted
- [x] 6.2 Add unit test for `_build_bot_gates()` verifying per-bot gate status derivation (blocked→fail, active→pass, idle→warn)
- [x] 6.3 Run existing test suite: `pytest hbot/tests/ -x -q` to verify no regressions
- [x] 6.4 Restart docker containers and verify bot gates appear in dashboard
