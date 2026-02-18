"""
CCXT helper for dynamic mean-reversion grids.

This module is intentionally decoupled from Hummingbot controller runtime and
can be used by worker processes consuming controller webhooks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import ccxt


@dataclass
class GridLevel:
    price: float
    amount: float
    side: str  # "buy" | "sell"


def build_grid_levels(
    mid_price: float,
    band_pct: float,
    levels: int,
    total_notional: float,
    side_bias: str,
) -> List[GridLevel]:
    if levels < 2:
        levels = 2
    half = levels // 2
    low = mid_price * (1.0 - band_pct)
    high = mid_price * (1.0 + band_pct)
    step = (high - low) / max(1, levels - 1)
    per_level_notional = total_notional / levels

    rows: List[GridLevel] = []
    for i in range(levels):
        px = low + i * step
        amount = per_level_notional / max(px, 1e-8)
        side = "buy" if i < half else "sell"
        if side_bias == "long" and i >= half:
            side = "sell"
        if side_bias == "short" and i < half:
            side = "buy"
        rows.append(GridLevel(price=px, amount=amount, side=side))
    return rows


def place_grid_orders(
    exchange: ccxt.Exchange,
    symbol: str,
    levels: List[GridLevel],
    params: dict | None = None,
) -> list:
    out = []
    params = params or {}
    for level in levels:
        if level.side == "buy":
            order = exchange.create_limit_buy_order(symbol, level.amount, level.price, params=params)
        else:
            order = exchange.create_limit_sell_order(symbol, level.amount, level.price, params=params)
        out.append(order)
    return out
