# EPP v2.4 Strategy Specification

## Purpose
Formalize EPP v2.4 Phase-0 behavior for active and no-trade variants.

## Scope
- Bot A (`variant: a`) active inventory engine.
- Bot D (`variant: d`) no-trade monitor/capital parking.

## Regime Framework
- `neutral_low_vol`
- `up`
- `down`
- `high_vol_shock`

Each regime defines spread bounds, levels, refresh timing, target base, and one-sided behavior.

## Key Mechanics
- Spread floor recompute with fee + slippage + adverse drift + turnover penalty.
- Inventory skew from base allocation error.
- Edge gating:
  - pause when net edge drops below pause threshold, resume only above resume threshold.
  - minimum state hold time prevents rapid run/pause flapping.
  - net edge model uses `fill_factor` (expected spread capture fraction) so the spread floor must be
    computed consistently: \(\text{spread} \ge (\text{costs} + \text{min\_edge}) / \text{fill\_factor}\)
- Cancel budget adaptation reduces churn.
- Hard risk vetoes: base allocation band, daily turnover hard cap, daily loss/drawdown hard limits.
- Quote hygiene: enforce exchange increments and avoid quoting tighter than top-of-book half-spread.

## Execution Modes

**Paper mode** (internal adapter, Level 2):
- Controller uses `connector_name: bitget_paper_trade`.
- `conf_client.yml` enables `paper_trade_exchanges: [bitget]`.
- Orders are simulated by `PaperExecutionAdapter` + depth-aware partial fill model; no exchange orders are sent.
- Adapter exposes strict `trading_rules` and in-flight tracking for V2 executors (no permissive fallback rules).
- Real market data/order book is read from canonical connector (`bitget`) to keep paper validation close to live.
- Bitget spot account must have some balance (even 2 USDT) so connector readiness checks pass.

**Live mode**:
- Connector readiness and balance checks enforced.
- Real orders placed via the `bitget` connector.
- Promotion from paper: single field change (`connector_name: bitget_paper_trade` -> `bitget`).

## Inputs / Outputs
- Inputs: mid price, balances, trading rules.
- Outputs: spread/size runtime config, state transitions, CSV logs.

## Fee Resolution
- Shared profile source: `hbot/config/fee_profiles.json`
- Resolution modes:
  - `auto`: exchange API (Bitget user fee) -> connector runtime fee info -> project profile fallback
  - `project`: project profile only
  - `manual`: `spot_fee_pct` from controller YAML
- Guard behavior:
  - if `require_fee_resolution: true` and no runtime/profile fee resolves, controller enters hard stop (`fee_unresolved`)

## Source of Truth
- `hbot/controllers/epp_v2_4.py`
- `hbot/controllers/paper_engine.py`
- `hbot/services/common/fee_provider.py`
- `hbot/controllers/ops_guard.py`
- `hbot/controllers/price_buffer.py`

## Owner
- Strategy Engineering
- Last-updated: 2026-02-20

