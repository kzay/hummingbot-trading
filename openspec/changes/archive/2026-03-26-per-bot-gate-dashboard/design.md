## Context

The realtime dashboard gate board currently shows 8 universal gates identically for every bot instance. These gates (controller_state, risk_reasons, order_book, edge, spread, spread_cap, pnl_governor, orders) are built by `_build_quote_gate_summary()` in `_helpers.py` and displayed in `BotGateBoardPanel.tsx`.

**Current data flow**: Bot controllers → `tick_emitter.py` (CSV with `bot*_gate_state` columns) + `telemetry_mixin.py` (Redis stream WITHOUT bot-specific fields) → `realtime_ui_api/state.py` → `_helpers.py` → API → frontend.

**Strategy types**: Bot1 = market-making (inherits `StrategyRuntimeV24Config`). Bot5/6/7 = directional (inherit `DirectionalStrategyRuntimeV24Config`). Spread/edge gates are meaningless for directional bots.

**Gap**: Bot-specific gate data exists in `processed_data` and CSV but is NOT included in the Redis telemetry payload or the API response.

## Goals / Non-Goals

**Goals:**
- Filter universal gates by strategy type so directional bots don't show irrelevant MM gates
- Surface per-bot gate state, reason, signal side, signal score in the dashboard
- Surface key strategy-specific indicators (bot6 CVD metrics, bot7 ADX/RSI) as informational gates
- Keep existing `quote_gates` array backward-compatible (additive only)

**Non-Goals:**
- Config-driven gate definitions (hardcode per-bot gate sets for now; genericize later)
- Historical gate timeline or gate change events
- Per-bot gate alerting rules
- Frontend gate editing or threshold overrides

## Decisions

### 1. Strategy type tag on telemetry payload

**Decision**: Add `strategy_type: "mm" | "directional"` to the telemetry payload in `telemetry_mixin.py`.

**Rationale**: The API needs to know which universal gates to include. Deriving strategy type from the instance name (e.g., "bot1" → mm) is fragile. The controller already knows its type via its config base class. Adding it to the payload is clean and self-describing.

**Alternative considered**: Hardcode a mapping in `_helpers.py` (bot1=mm, bot5/6/7=directional). Rejected — breaks when new bots are added.

### 2. Include bot-specific fields in telemetry payload

**Decision**: Add a `bot_gates` dict to the telemetry payload containing each bot's `_bot*_gate_metrics()` output, keyed by the bot prefix (e.g., `"bot1"`, `"bot6"`).

**Implementation**: In `telemetry_mixin.py`, after building the base payload, call `getattr(self, f"_bot{N}_gate_metrics", None)` for the active bot and include the result.

**Alternative considered**: Forward all `bot*_` fields from `processed_data` as flat keys. Rejected — pollutes the payload with 30+ unstructured fields.

### 3. Strategy-aware universal gate filtering in `_helpers.py`

**Decision**: `_build_quote_gate_summary()` accepts an optional `strategy_type` parameter. When `strategy_type == "directional"`, omit gates: `edge`, `spread`, `spread_cap`. When `strategy_type == "mm"`, include all gates. Default (None) keeps all gates for backward compatibility.

**Rationale**: These gates compute spread/edge metrics that directional strategies don't produce — showing "0.000000 / 0.000000" is confusing, not helpful.

### 4. New `bot_gates` array in API response

**Decision**: Add `bot_gates` array to `SummaryAccount` alongside existing `quote_gates`. Each entry:
```json
{
  "bot_id": "bot6",
  "strategy_type": "directional",
  "gates": [
    {"key": "gate_state", "label": "Bot6 signal gate", "status": "pass", "detail": "active"},
    {"key": "signal_score", "label": "Signal score", "status": "info", "detail": "0.85"},
    {"key": "cvd_divergence", "label": "CVD divergence", "status": "info", "detail": "0.042"}
  ]
}
```

**Rationale**: Reuses the same `{key, label, status, detail}` gate shape — frontend can render them with existing gate row logic. Grouping by `bot_id` lets the panel show collapsible per-bot sections.

### 5. Frontend: collapsible bot sections in BotGateBoardPanel

**Decision**: Below the universal gates table, render one collapsible section per bot in `bot_gates`. Each section shows the bot's strategy-specific gates. Use the same table/row markup for consistency.

**Alternative considered**: Separate panel per bot. Rejected — wastes screen real estate when multiple bots are active. A single panel with collapsible sections is more compact.

### 6. Bot gate definitions (hardcoded per bot)

**Decision**: Define per-bot gate extraction in `_helpers.py` as a simple mapping function:

| Bot | Strategy | Gates shown |
|-----|----------|------------|
| Bot1 | mm | gate_state, signal_side, signal_score |
| Bot5 | directional | gate_state, signal_side, signal_score, flow_conviction |
| Bot6 | directional | gate_state, signal_side, signal_score, cvd_divergence_ratio, adx, hedge_state |
| Bot7 | directional | gate_state, signal_side, signal_score, adx, rsi |

Each field maps to a gate entry with computed status (e.g., gate_state="blocked" → status="fail", signal_score > 0.7 → status="pass").

## Risks / Trade-offs

**[Risk] Telemetry payload size increase** → The `bot_gates` dict adds ~200-400 bytes per minute snapshot. Negligible vs the existing ~2KB payload. No mitigation needed.

**[Risk] `_bot*_gate_metrics()` may not exist on all controller instances** → Mitigation: `getattr(self, method_name, None)` with fallback to empty dict. Already safe.

**[Risk] Frontend rendering when no bot_gates present** → Mitigation: Conditionally render the bot section only when `bot_gates` array is non-empty. Existing instances without the field show current behavior.

**[Trade-off] Hardcoded bot gate definitions vs config-driven** → Chose hardcoded for speed. Can be extracted to a registry pattern later if bot count grows beyond ~10.
