## Why

The dashboard gate board shows 8 universal gates (spread, edge, order_book, etc.) identically for every bot instance. But Bot1 is market-making while Bot5/6/7 are directional — spread and edge gates are meaningless for directional strategies, and bot-specific signals (CVD divergence, flow conviction, ADX/RSI) are invisible. Operators cannot diagnose why a specific bot is blocked without SSH-ing into CSV logs.

## What Changes

- **Strategy-aware universal gates**: Only show gates relevant to the bot's strategy type. MM bots (Bot1) keep spread/edge/spread_cap gates. Directional bots (Bot5/6/7) skip those and show position/signal-related gates instead.
- **Per-bot gate section**: Surface each bot's own gate metrics (`bot*_gate_state`, `bot*_gate_reason`, signal scores, strategy-specific indicators) in the dashboard alongside the universal gates.
- **Telemetry pipeline extension**: Include bot-specific gate fields in the Redis stream payload so the API can serve them without reading CSV.
- **API response extension**: Add a `bot_gates` array to the summary payload, with each entry tagged by bot ID and strategy type.
- **Frontend per-bot rendering**: `BotGateBoardPanel` renders bot-specific gates conditionally, grouped by bot, with strategy-appropriate labels and thresholds.

## Capabilities

### New Capabilities
- `per-bot-gates`: Strategy-aware gate rendering — filter universal gates by strategy type (MM vs directional), surface bot-specific gate state/reason/signal data in the dashboard.

### Modified Capabilities
_(none — no existing spec-level requirements change)_

## Impact

- **Backend**: `_helpers.py` (`_build_quote_gate_summary`), `state.py` (payload storage), `main.py` (API response shape)
- **Telemetry**: `telemetry_mixin.py` (include bot-specific fields in Redis stream)
- **Frontend**: `BotGateBoardPanel.tsx`, `useDashboardStore.ts`, `realtime.ts` (types), `presentation.ts` (gate tone/priority for new gates)
- **Bot controllers**: `bot1/baseline_v1.py`, `bot5/ift_jota_v1.py`, `bot6/cvd_divergence_v1.py`, `bot7/adaptive_grid_v1.py` — no logic changes, just ensuring `_bot*_gate_metrics()` output is included in telemetry
- **No breaking changes**: existing `quote_gates` array remains; `bot_gates` is additive
