"""Regime detection for EPP v2.4.

Classifies market conditions into one of five regimes based on EMA trend,
ATR volatility band, and adverse drift, with regime-hold anti-flap logic.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Optional, Tuple

from controllers.runtime.market_making_types import RegimeSpec

_ZERO = Decimal("0")
_ONE = Decimal("1")


class RegimeDetector:
    """Regime classifier with regime-hold anti-flap state.

    Examines pre-computed EMA trend, ATR band, and short-term drift to
    classify the market into one of five regimes.  A regime hold counter
    prevents premature switching on transient signals.
    """

    def __init__(
        self,
        specs: Dict[str, RegimeSpec],
        high_vol_band_pct: Decimal,
        shock_drift_30s_pct: Decimal,
        shock_drift_atr_multiplier: Decimal = Decimal("1.25"),
        trend_eps_pct: Decimal = Decimal("0.0010"),
        regime_hold_ticks: int = 3,
    ):
        self._specs = specs
        self._high_vol_band_pct = high_vol_band_pct
        self._shock_drift_30s_pct = shock_drift_30s_pct
        self._shock_drift_atr_multiplier = shock_drift_atr_multiplier
        self._trend_eps_pct = trend_eps_pct
        self._regime_hold_ticks = regime_hold_ticks

        self._active_regime: str = "neutral_low_vol"
        self._pending_regime: str = "neutral_low_vol"
        self._regime_hold_counter: int = 0
        self._regime_source: str = "price_buffer"
        self._changed_one_sided: Optional[str] = None

    @property
    def active_regime(self) -> str:
        return self._active_regime

    @property
    def regime_source(self) -> str:
        return self._regime_source

    @property
    def changed_one_sided(self) -> Optional[str]:
        """Old one_sided value when a regime transition changed it; ``None`` otherwise."""
        return self._changed_one_sided

    def detect(
        self,
        mid: Decimal,
        ema_val: Optional[Decimal],
        band_pct: Decimal,
        drift: Decimal,
        regime_source_tag: str = "price_buffer",
    ) -> Tuple[str, RegimeSpec]:
        """Classify market regime and apply hold-counter anti-flap.

        Returns ``(regime_name, regime_spec)``.

        After calling, check :attr:`changed_one_sided` for the old
        ``one_sided`` value if a one-sided transition occurred.
        """
        self._regime_source = regime_source_tag
        self._changed_one_sided = None

        vol_adaptive_shock = (
            band_pct * self._shock_drift_atr_multiplier
            if band_pct > _ZERO
            else self._shock_drift_30s_pct
        )
        shock_threshold = min(self._shock_drift_30s_pct, vol_adaptive_shock)

        if band_pct >= self._high_vol_band_pct or drift >= shock_threshold:
            raw_regime = "high_vol_shock"
        elif ema_val is None:
            raw_regime = "neutral_low_vol"
        elif mid > ema_val * (_ONE + self._trend_eps_pct):
            raw_regime = "up"
        elif mid < ema_val * (_ONE - self._trend_eps_pct):
            raw_regime = "down"
        else:
            raw_regime = "neutral_low_vol"

        high_vol_mid_threshold = self._high_vol_band_pct * Decimal("0.5")
        if band_pct >= high_vol_mid_threshold and raw_regime == "neutral_low_vol":
            raw_regime = "neutral_high_vol"

        if raw_regime == self._pending_regime:
            self._regime_hold_counter += 1
        else:
            self._pending_regime = raw_regime
            self._regime_hold_counter = 1

        if (
            raw_regime != self._active_regime
            and self._regime_hold_counter >= self._regime_hold_ticks
        ):
            old_one_sided = self._specs[self._active_regime].one_sided
            new_one_sided = self._specs[raw_regime].one_sided
            self._active_regime = raw_regime
            if old_one_sided != new_one_sided:
                self._changed_one_sided = old_one_sided

        return self._active_regime, self._specs[self._active_regime]
