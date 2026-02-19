# Financial Specification

## Purpose
Define economic assumptions and accounting conventions used for strategy evaluation.

## Scope
Phase-0 EPP and external orchestration operation.

## Assumptions
- VIP0 fee model:
  - spot maker/taker ~0.10%
  - perpetual maker/taker as configured in fee overrides
- Slippage modeled conservatively via controller parameters.

## Core Budget Constraints
- Daily turnover target: `< 3.0x` equity (ideal `< 2.0x`).
- Fee-to-gross-profit target: `< 35-40%`.
- Validation drawdown target: `< 3-4%` in phase windows.

## Accounting Conventions
- Equity in quote currency.
- Turnover = traded_notional_today / equity_quote.
- PnL tracked through controller daily/minute/fill logs.

## Source of Truth
- `hbot/controllers/epp_v2_4.py`
- `hbot/data/bot*/conf/conf_fee_overrides.yml`
- `hbot/README.md` validation criteria

## Owner
- Trading/Research
- Last-updated: 2026-02-19

