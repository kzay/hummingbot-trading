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
  - net edge <= 0 -> soft pause behavior.
- Cancel budget adaptation reduces churn.

## Execution Modes

**Paper mode** (`paper_mode: true` in controller YAML):
- Controller uses real `bitget` connector for market data only (mid-price, order book).
- Balances tracked internally via `paper_start_quote` / `paper_start_base`.
- No orders placed on the exchange.
- `connector_name` stays `bitget` (the V2 framework's `MarketDataProvider` cannot
  resolve `bitget_paper_trade` as a module -- framework paper trade only works for
  standalone `ScriptStrategyBase` scripts).
- Bitget spot account must have some balance (even 2 USDT) so the connector's
  `account_balance` readiness check passes.

**Live mode** (`paper_mode: false`):
- Connector readiness and balance checks enforced.
- Real orders placed via the `bitget` connector.
- Promotion from paper: single field change (`paper_mode: true` -> `false`).

## Inputs / Outputs
- Inputs: mid price, balances, trading rules.
- Outputs: spread/size runtime config, state transitions, CSV logs.

## Source of Truth
- `hbot/controllers/epp_v2_4.py`
- `hbot/controllers/ops_guard.py`
- `hbot/controllers/price_buffer.py`

## Owner
- Strategy Engineering
- Last-updated: 2026-02-19

