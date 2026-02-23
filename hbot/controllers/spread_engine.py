"""Spread computation engine for EPP v2.4.

Computes spread percentages, per-level spread arrays, and spread floors
given regime specs, turnover, and cost parameters.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Tuple

from controllers.epp_v2_4 import RegimeSpec, _clip


class SpreadEngine:
    """Computes spreads, levels, and spread floors from regime and cost inputs."""

    def __init__(
        self,
        turnover_cap_x: Decimal,
        spread_step_multiplier: Decimal,
        vol_penalty_multiplier: Decimal,
    ):
        self._turnover_cap_x = turnover_cap_x
        self._spread_step_multiplier = spread_step_multiplier
        self._vol_penalty_multiplier = vol_penalty_multiplier

    def pick_spread_pct(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> Decimal:
        """Interpolate spread between regime min/max based on turnover ratio."""
        ratio = _clip(
            turnover_x / max(self._turnover_cap_x, Decimal("0.0001")),
            Decimal("0"),
            Decimal("1"),
        )
        return regime_spec.spread_min + (regime_spec.spread_max - regime_spec.spread_min) * ratio

    def pick_levels(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> int:
        """Choose number of order levels based on turnover ratio."""
        if regime_spec.levels_min == regime_spec.levels_max:
            return regime_spec.levels_min
        ratio = _clip(
            turnover_x / max(self._turnover_cap_x, Decimal("0.0001")),
            Decimal("0"),
            Decimal("1"),
        )
        span = regime_spec.levels_max - regime_spec.levels_min
        return max(regime_spec.levels_min, int(regime_spec.levels_max - int(round(float(ratio) * span))))

    def build_side_spreads(
        self,
        spread_pct: Decimal,
        skew: Decimal,
        levels: int,
        one_sided: str,
        min_side_spread: Decimal,
    ) -> Tuple[List[Decimal], List[Decimal]]:
        """Build per-level buy and sell spread arrays with skew and one-sided filtering."""
        half = spread_pct / Decimal("2")
        step = half * self._spread_step_multiplier
        buy: List[Decimal] = []
        sell: List[Decimal] = []
        for i in range(levels):
            level_offset = half + step * Decimal(i)
            buy.append(max(min_side_spread, level_offset - skew))
            sell.append(max(min_side_spread, level_offset + skew))
        if one_sided == "buy_only":
            sell = []
        elif one_sided == "sell_only":
            buy = []
        return buy, sell

    def compute_spread_floor(
        self,
        maker_fee_pct: Decimal,
        slippage_est_pct: Decimal,
        adverse_drift: Decimal,
        turnover_penalty: Decimal,
        min_edge_threshold: Decimal,
        fill_factor: Decimal,
        vol_band_pct: Decimal,
    ) -> Decimal:
        """Compute the minimum spread that clears the edge gate.

        ``spread >= (costs + min_edge) / fill_factor + vol_penalty``
        """
        base_costs = (
            maker_fee_pct
            + slippage_est_pct
            + max(Decimal("0"), adverse_drift)
            + turnover_penalty
        )
        vol_penalty = vol_band_pct * self._vol_penalty_multiplier
        return (base_costs + min_edge_threshold) / fill_factor + vol_penalty
