"""Spread computation engine for EPP v2.4.

Computes spread percentages, per-level spread arrays, spread floors,
and the full spread/edge state given regime specs, turnover, and cost
parameters.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Tuple

from controllers.core import RegimeSpec, RuntimeLevelState, SpreadEdgeState, clip

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")
_10K = Decimal("10000")
_MIN_SPREAD = Decimal("0.0001")
_MIN_SKEW_CAP = Decimal("0.0005")
_FILL_FACTOR_LO = Decimal("0.05")


class SpreadEngine:
    """Computes spreads, levels, spread floors, and full edge state."""

    def __init__(
        self,
        turnover_cap_x: Decimal,
        spread_step_multiplier: Decimal,
        vol_penalty_multiplier: Decimal,
        *,
        high_vol_band_pct: Decimal = Decimal("0.0080"),
        trend_skew_factor: Decimal = Decimal("0.8"),
        neutral_skew_factor: Decimal = Decimal("0.5"),
        inventory_skew_cap_pct: Decimal = Decimal("0.0030"),
        inventory_skew_vol_multiplier: Decimal = Decimal("1.0"),
        slippage_est_pct: Decimal = Decimal("0.0005"),
        min_net_edge_bps: int = 1,
        edge_resume_bps: int = 4,
        drift_spike_threshold_bps: int = 5,
        drift_spike_mult_max: Decimal = Decimal("1.8"),
        adverse_fill_spread_multiplier: Decimal = Decimal("1.3"),
        adverse_fill_count_threshold: int = 20,
        turnover_penalty_step: Decimal = Decimal("0.0010"),
        adaptive_vol_spread_widen_max: Decimal = Decimal("0.35"),
    ):
        self._turnover_cap_x = turnover_cap_x
        self._spread_step_multiplier = spread_step_multiplier
        self._vol_penalty_multiplier = vol_penalty_multiplier
        self._high_vol_band_pct = high_vol_band_pct
        self._trend_skew_factor = trend_skew_factor
        self._neutral_skew_factor = neutral_skew_factor
        self._inventory_skew_cap_pct = inventory_skew_cap_pct
        self._inventory_skew_vol_multiplier = inventory_skew_vol_multiplier
        self._slippage_est_pct = slippage_est_pct
        self._min_net_edge_bps = min_net_edge_bps
        self._edge_resume_bps = edge_resume_bps
        self._drift_spike_threshold_bps = drift_spike_threshold_bps
        self._drift_spike_mult_max = drift_spike_mult_max
        self._adverse_fill_spread_multiplier = adverse_fill_spread_multiplier
        self._adverse_fill_count_threshold = adverse_fill_count_threshold
        self._turnover_penalty_step = turnover_penalty_step
        self._adaptive_vol_spread_widen_max = adaptive_vol_spread_widen_max

    # ------------------------------------------------------------------
    # Existing public methods (backward-compatible signatures)
    # ------------------------------------------------------------------

    def pick_spread_pct(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> Decimal:
        """Interpolate spread between regime min/max based on turnover ratio."""
        ratio = clip(
            turnover_x / max(self._turnover_cap_x, Decimal("0.0001")),
            _ZERO,
            _ONE,
        )
        return regime_spec.spread_min + (regime_spec.spread_max - regime_spec.spread_min) * ratio

    def pick_levels(self, regime_spec: RegimeSpec, turnover_x: Decimal) -> int:
        """Choose number of order levels based on turnover ratio."""
        if regime_spec.levels_min == regime_spec.levels_max:
            return regime_spec.levels_min
        ratio = clip(
            turnover_x / max(self._turnover_cap_x, Decimal("0.0001")),
            _ZERO,
            _ONE,
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
        half = spread_pct / _TWO
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
        """Compute the minimum spread that clears the edge gate."""
        base_costs = (
            maker_fee_pct
            + slippage_est_pct
            + max(_ZERO, adverse_drift)
            + turnover_penalty
        )
        vol_penalty = vol_band_pct * self._vol_penalty_multiplier
        return (base_costs + min_edge_threshold) / fill_factor + vol_penalty

    # ------------------------------------------------------------------
    # Full spread + edge computation (extracted from EppV24Controller)
    # ------------------------------------------------------------------

    def compute_spread_and_edge(
        self,
        regime_name: str,
        regime_spec: RegimeSpec,
        band_pct: Decimal,
        raw_drift: Decimal,
        smooth_drift: Decimal,
        target_base_pct: Decimal,
        base_pct: Decimal,
        equity_quote: Decimal,
        traded_notional_today: Decimal,
        ob_imbalance: Decimal,
        ob_imbalance_skew_weight: Decimal,
        maker_fee_pct: Decimal,
        is_perp: bool,
        funding_rate: Decimal,
        adverse_fill_count: int,
        fill_edge_ewma: Optional[Decimal],
        override_spread_pct: Optional[Decimal] = None,
        min_edge_threshold_override_pct: Optional[Decimal] = None,
        market_spread_floor_pct: Optional[Decimal] = None,
        adaptive_vol_ratio: Optional[Decimal] = None,
    ) -> Tuple[SpreadEdgeState, Decimal]:
        """Compute spread, edge, skew, and spread floor.

        Returns ``(spread_edge_state, spread_floor_pct)``.
        """
        vol_ratio = clip(
            band_pct / max(self._high_vol_band_pct, _MIN_SPREAD),
            _ZERO,
            _ONE,
        )
        skew_factor = self._trend_skew_factor if regime_name in {"up", "down"} else self._neutral_skew_factor
        inv_error = target_base_pct - base_pct
        skew_scale = _ONE + self._inventory_skew_vol_multiplier * vol_ratio
        skew_cap = max(_MIN_SKEW_CAP, self._inventory_skew_cap_pct)
        inventory_skew = clip(inv_error * skew_factor * skew_scale, -skew_cap, skew_cap)

        ob_skew = _ZERO
        if ob_imbalance_skew_weight > _ZERO:
            ob_skew = clip(
                ob_imbalance * ob_imbalance_skew_weight * skew_cap,
                -skew_cap * Decimal("0.5"),
                skew_cap * Decimal("0.5"),
            )
        skew = clip(inventory_skew + ob_skew, -skew_cap, skew_cap)

        drift_excess_bps = max(_ZERO, (raw_drift - smooth_drift) * _10K)
        drift_spike_bps = max(_ONE, Decimal(self._drift_spike_threshold_bps))
        mult_range = max(_ZERO, self._drift_spike_mult_max - _ONE)
        drift_spread_mult = _ONE + clip(drift_excess_bps / drift_spike_bps, _ZERO, _ONE) * mult_range

        turnover_x = traded_notional_today / equity_quote if equity_quote > _ZERO else _ZERO
        turnover_penalty = max(_ZERO, turnover_x - self._turnover_cap_x) * self._turnover_penalty_step

        vol_penalty = band_pct * self._vol_penalty_multiplier
        min_edge_threshold = (
            min_edge_threshold_override_pct
            if min_edge_threshold_override_pct is not None
            else Decimal(self._min_net_edge_bps) / _10K
        )
        edge_resume_threshold = Decimal(self._edge_resume_bps) / _10K
        fill_factor = clip(regime_spec.fill_factor, _FILL_FACTOR_LO, _ONE)

        funding_cost_bps = _ZERO
        if is_perp and funding_rate != _ZERO:
            # Perpetual funding semantics: when funding_rate > 0, longs pay shorts;
            # when funding_rate < 0, shorts pay longs. Cost is always non-negative.
            # Long position (base_pct >= 0): sign = +1 → cost when funding_rate > 0.
            # Short position (base_pct < 0): sign = -1 → cost when funding_rate < 0.
            sign = _ONE if base_pct >= _ZERO else Decimal("-1")
            funding_cost_bps = max(_ZERO, sign * funding_rate * _10K)
        funding_cost_pct = funding_cost_bps / _10K

        base_costs = (
            maker_fee_pct
            + self._slippage_est_pct
            + max(_ZERO, smooth_drift)
            + turnover_penalty
            + funding_cost_pct
        )
        spread_floor_pct = (base_costs + min_edge_threshold) / fill_factor + vol_penalty
        if market_spread_floor_pct is not None and market_spread_floor_pct > _ZERO:
            spread_floor_pct = max(spread_floor_pct, market_spread_floor_pct)

        if override_spread_pct is not None:
            spread_pct = max(_ZERO, override_spread_pct)
        else:
            spread_pct = self.pick_spread_pct(regime_spec, turnover_x)
        spread_pct = max(spread_pct, spread_floor_pct)
        spread_pct = spread_pct * drift_spread_mult
        if adaptive_vol_ratio is not None and adaptive_vol_ratio > _ZERO:
            vol_widen = _ONE + clip(adaptive_vol_ratio, _ZERO, _ONE) * self._adaptive_vol_spread_widen_max
            spread_pct = spread_pct * vol_widen

        adverse_fill_active = (
            adverse_fill_count >= self._adverse_fill_count_threshold
            and fill_edge_ewma is not None
        )
        if adverse_fill_active:
            spread_pct = spread_pct * self._adverse_fill_spread_multiplier

        net_edge = (
            fill_factor * spread_pct
            - maker_fee_pct
            - self._slippage_est_pct
            - max(_ZERO, smooth_drift)
            - turnover_penalty
            - funding_cost_pct
        )
        state = SpreadEdgeState(
            band_pct=band_pct,
            spread_pct=spread_pct,
            net_edge=net_edge,
            skew=skew,
            adverse_drift=raw_drift,
            smooth_drift=smooth_drift,
            drift_spread_mult=drift_spread_mult,
            turnover_x=turnover_x,
            min_edge_threshold=min_edge_threshold,
            edge_resume_threshold=edge_resume_threshold,
            fill_factor=fill_factor,
        )
        return state, spread_floor_pct

    # ------------------------------------------------------------------
    # Runtime level application (extracted from EppV24Controller)
    # ------------------------------------------------------------------

    def apply_runtime_spreads_and_sizing(
        self,
        runtime_levels: RuntimeLevelState,
        buy_spreads: List[Decimal],
        sell_spreads: List[Decimal],
        equity_quote: Decimal,
        mid: Decimal,
        quote_size_pct: Decimal,
        size_mult: Decimal,
        kelly_order_quote: Decimal,
        min_notional_quote: Decimal,
        min_base_amount: Decimal,
        max_order_notional_quote: Decimal,
        max_total_notional_quote: Decimal,
        cooldown_time: int,
        no_trade: bool,
        variant: str,
        enabled: bool,
    ) -> None:
        """Set spreads, amounts, and sizing on *runtime_levels* (mutated in-place)."""
        if no_trade or variant == "d":
            runtime_levels.buy_spreads = []
            runtime_levels.sell_spreads = []
            runtime_levels.buy_amounts_pct = []
            runtime_levels.sell_amounts_pct = []
            runtime_levels.total_amount_quote = _ZERO
            return
        if variant in {"b", "c"} or not enabled:
            runtime_levels.buy_spreads = []
            runtime_levels.sell_spreads = []
            runtime_levels.buy_amounts_pct = []
            runtime_levels.sell_amounts_pct = []
            runtime_levels.total_amount_quote = _ZERO
            return

        runtime_levels.buy_spreads = list(buy_spreads)
        runtime_levels.sell_spreads = list(sell_spreads)
        runtime_levels.buy_amounts_pct = self._equal_split_pct_values(len(buy_spreads))
        runtime_levels.sell_amounts_pct = self._equal_split_pct_values(len(sell_spreads))
        safe_mult = max(_ONE, size_mult)

        if kelly_order_quote > _ZERO:
            per_order_quote = kelly_order_quote
        else:
            scaled_quote_size_pct = max(_ZERO, quote_size_pct * safe_mult)
            per_order_quote = max(min_notional_quote, equity_quote * scaled_quote_size_pct)
        if max_order_notional_quote > _ZERO:
            per_order_quote = min(per_order_quote, max_order_notional_quote)
        side_levels = max(1, len(buy_spreads) + len(sell_spreads))
        total_amount_quote = per_order_quote * Decimal(side_levels)

        if min_base_amount > 0 and total_amount_quote > 0:
            base_for_total = total_amount_quote / mid
            if base_for_total < min_base_amount:
                total_amount_quote = min_base_amount * mid

        runtime_levels.executor_refresh_time = max(30, int(runtime_levels.executor_refresh_time))
        runtime_levels.cooldown_time = max(5, cooldown_time)
        if max_total_notional_quote > 0:
            total_amount_quote = min(total_amount_quote, max_total_notional_quote)
        runtime_levels.total_amount_quote = total_amount_quote

    @staticmethod
    def _equal_split_pct_values(level_count: int) -> List[Decimal]:
        if level_count <= 0:
            return []
        unit = Decimal("100") / Decimal(level_count)
        return [unit] * level_count
