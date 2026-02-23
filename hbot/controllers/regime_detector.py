"""Regime detection for EPP v2.4.

Classifies market conditions into one of four regimes based on EMA trend
and ATR volatility, returning the corresponding ``RegimeSpec``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Tuple

from controllers.epp_v2_4 import RegimeSpec, _clip
from controllers.price_buffer import MidPriceBuffer


class RegimeDetector:
    """Stateless regime classifier.

    Examines price buffer indicators (EMA trend, ATR band, short-term drift)
    and maps them to a ``RegimeSpec`` from the provided specs table.
    """

    def __init__(
        self,
        specs: Dict[str, RegimeSpec],
        high_vol_band_pct: Decimal,
        shock_drift_30s_pct: Decimal,
        trend_eps_pct: Decimal,
        ema_period: int,
        atr_period: int,
    ):
        self._specs = specs
        self._high_vol_band_pct = high_vol_band_pct
        self._shock_drift_30s_pct = shock_drift_30s_pct
        self._trend_eps_pct = trend_eps_pct
        self._ema_period = ema_period
        self._atr_period = atr_period

    def detect(
        self, mid: Decimal, price_buffer: MidPriceBuffer, now_ts: float
    ) -> Tuple[str, RegimeSpec]:
        """Return ``(regime_name, regime_spec)`` for the current market state."""
        ema_val = price_buffer.ema(self._ema_period)
        band_pct = price_buffer.band_pct(self._atr_period) or Decimal("0")
        drift = price_buffer.adverse_drift_30s(now_ts)

        if band_pct >= self._high_vol_band_pct or drift >= self._shock_drift_30s_pct:
            return "high_vol_shock", self._specs["high_vol_shock"]
        if ema_val is None:
            return "neutral_low_vol", self._specs["neutral_low_vol"]
        if mid > ema_val * (Decimal("1") + self._trend_eps_pct):
            return "up", self._specs["up"]
        if mid < ema_val * (Decimal("1") - self._trend_eps_pct):
            return "down", self._specs["down"]
        return "neutral_low_vol", self._specs["neutral_low_vol"]
