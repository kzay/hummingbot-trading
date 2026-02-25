"""EPP v2.4 strategy adapter for the generic backtest harness.

Thin wrapper that converts bar data into market-making order intents
using the extracted spread engine and regime detector.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List

from controllers.core import RegimeSpec, clip
from controllers.epp_v2_4 import EppV24Controller
from controllers.price_buffer import MidPriceBuffer
from controllers.regime_detector import RegimeDetector
from controllers.spread_engine import SpreadEngine
from scripts.backtest.harness.data_provider import BarData
from scripts.backtest.harness.strategy_adapter import BacktestState, OrderIntent
from services.common.utils import to_decimal


class EppV24Adapter:
    """Backtest adapter for EPP v2.4 market making strategy.

    Uses the extracted ``RegimeDetector`` and ``SpreadEngine`` modules
    for stateless spread/level computation.  Inventory skew is simplified
    to a fixed target base pct.
    """

    def __init__(
        self,
        target_base_pct: Decimal = Decimal("0.5"),
        quote_size_pct: Decimal = Decimal("0.001"),
        ema_period: int = 50,
        atr_period: int = 14,
        turnover_cap_x: Decimal = Decimal("3.0"),
        spread_step_multiplier: Decimal = Decimal("0.4"),
        high_vol_band_pct: Decimal = Decimal("0.008"),
        shock_drift_30s_pct: Decimal = Decimal("0.01"),
        trend_eps_pct: Decimal = Decimal("0.001"),
    ):
        self._target_base_pct = target_base_pct
        self._quote_size_pct = quote_size_pct
        self._price_buffer = MidPriceBuffer(sample_interval_sec=10)
        self._regime_detector = RegimeDetector(
            specs=EppV24Controller.PHASE0_SPECS,
            high_vol_band_pct=high_vol_band_pct,
            shock_drift_30s_pct=shock_drift_30s_pct,
            trend_eps_pct=trend_eps_pct,
            ema_period=ema_period,
            atr_period=atr_period,
        )
        self._spread_engine = SpreadEngine(
            turnover_cap_x=turnover_cap_x,
            spread_step_multiplier=spread_step_multiplier,
            vol_penalty_multiplier=Decimal("0.5"),
        )

    @property
    def strategy_name(self) -> str:
        return "epp_v2_4"

    def process_bar(self, bar: BarData, state: BacktestState) -> List[OrderIntent]:
        self._price_buffer.add_sample(bar.timestamp_s, bar.mid_price)

        regime_name, regime_spec = self._regime_detector.detect(
            bar.mid_price, self._price_buffer, bar.timestamp_s
        )
        state.strategy_state["regime"] = regime_name

        turnover_x = Decimal("0")
        spread_pct = self._spread_engine.pick_spread_pct(regime_spec, turnover_x)
        levels = self._spread_engine.pick_levels(regime_spec, turnover_x)

        inv_error = self._target_base_pct - state.base_pct
        skew = clip(inv_error * Decimal("0.5"), Decimal("-0.003"), Decimal("0.003"))

        buy_spreads, sell_spreads = self._spread_engine.build_side_spreads(
            spread_pct, skew, levels, regime_spec.one_sided, Decimal("0.0001"),
        )

        equity = state.equity_quote if state.equity_quote > 0 else Decimal("1000")
        per_order_quote = equity * self._quote_size_pct

        intents: List[OrderIntent] = []
        for i, s in enumerate(buy_spreads):
            price = bar.mid_price * (Decimal("1") - s)
            amount = per_order_quote / price if price > 0 else Decimal("0")
            intents.append(OrderIntent(
                side="buy", price=price, amount=amount,
                order_type="limit_maker", level_id=f"buy_{i}",
            ))
        for i, s in enumerate(sell_spreads):
            price = bar.mid_price * (Decimal("1") + s)
            amount = per_order_quote / price if price > 0 else Decimal("0")
            intents.append(OrderIntent(
                side="sell", price=price, amount=amount,
                order_type="limit_maker", level_id=f"sell_{i}",
            ))

        state.strategy_state["spread_pct"] = str(spread_pct)
        state.strategy_state["levels"] = levels
        return intents
