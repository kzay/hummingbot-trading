"""ICTState -- unified facade for all ICT detectors.

Single entry point for the full ICT indicator pipeline.  Call ``add_bar``
once per candle; detectors are wired together automatically (e.g.
SwingDetector -> StructureDetector -> OrderBlockDetector).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from controllers.common.ict._types import (
    DisplacementEvent,
    FVGEvent,
    LiquidityPool,
    OrderBlockEvent,
    StructureEvent,
    SwingEvent,
    VolumeImbalanceEvent,
)
from controllers.common.ict.breaker import BreakerBlockTracker
from controllers.common.ict.displacement import DisplacementDetector
from controllers.common.ict.fvg import FVGDetector
from controllers.common.ict.liquidity import LiquidityDetector
from controllers.common.ict.order_block import OrderBlockDetector
from controllers.common.ict.ote import OTEDetector
from controllers.common.ict.premium_discount import PremiumDiscountZone
from controllers.common.ict.structure import StructureDetector
from controllers.common.ict.swing import SwingDetector
from controllers.common.ict.volume_imbalance import VolumeImbalanceDetector

_ZERO = Decimal("0")


@dataclass
class ICTConfig:
    """Plain dataclass (not frozen) so it can be embedded in Pydantic bot configs."""

    swing_length: int = 10
    fvg_decay_bars: int = 10
    fvg_max_active: int = 20
    ob_max_active: int = 15
    ob_max_age: int = 50
    liquidity_range_pct: Decimal = field(default_factory=lambda: Decimal("0.01"))
    liquidity_min_touches: int = 2
    displacement_atr_mult: Decimal = field(default_factory=lambda: Decimal("2.0"))
    atr_period: int = 14
    vi_max_active: int = 20
    vi_decay_bars: int = 15


class ICTState:
    """Unified ICT indicator pipeline.

    Wires all detectors together in dependency order:
      SwingDetector
        -> StructureDetector, LiquidityDetector, PremiumDiscountZone, OTEDetector
      StructureDetector
        -> OrderBlockDetector
      OrderBlockDetector (mitigated events)
        -> BreakerBlockTracker
      FVGDetector, DisplacementDetector, VolumeImbalanceDetector run independently.
    """

    __slots__ = (
        "_bar_idx",
        "_breaker",
        "_config",
        "_displacement",
        "_fvg",
        "_liquidity",
        "_ob",
        "_ote",
        "_premium_discount",
        "_structure",
        "_swing",
        "_vi",
    )

    def __init__(self, config: ICTConfig | None = None) -> None:
        cfg = config or ICTConfig()
        self._config = cfg
        self._swing = SwingDetector(length=cfg.swing_length)
        self._fvg = FVGDetector(
            decay_bars=cfg.fvg_decay_bars,
            max_active=cfg.fvg_max_active,
        )
        self._structure = StructureDetector()
        self._ob = OrderBlockDetector(
            max_active=cfg.ob_max_active,
            max_age=cfg.ob_max_age,
        )
        self._liquidity = LiquidityDetector(
            range_pct=cfg.liquidity_range_pct,
            min_touches=cfg.liquidity_min_touches,
        )
        self._displacement = DisplacementDetector(
            atr_period=cfg.atr_period,
            atr_mult=cfg.displacement_atr_mult,
        )
        self._premium_discount = PremiumDiscountZone()
        self._ote = OTEDetector()
        self._vi = VolumeImbalanceDetector(
            max_active=cfg.vi_max_active,
            decay_bars=cfg.vi_decay_bars,
        )
        self._breaker = BreakerBlockTracker()
        self._bar_idx: int = 0

    def add_bar(
        self,
        open_: Decimal,
        high: Decimal,
        low: Decimal,
        close: Decimal,
        volume: Decimal = _ZERO,
    ) -> None:
        """Feed one OHLCV bar through the entire ICT pipeline."""
        self._bar_idx += 1

        # Independent detectors
        self._fvg.add_bar(open_, high, low, close, volume)
        self._displacement.add_bar(open_, high, low, close, volume)
        self._vi.add_bar(open_, high, low, close, volume)

        # Swing -> dependent detectors
        swing_event = self._swing.add_bar(open_, high, low, close, volume)
        self._structure.add_bar(open_, high, low, close, volume)
        self._ob.add_bar(open_, high, low, close, volume)
        self._liquidity.add_bar(open_, high, low, close, volume)
        self._premium_discount.add_bar(open_, high, low, close, volume)
        self._ote.add_bar(open_, high, low, close, volume)
        self._breaker.add_bar(open_, high, low, close, volume)

        if swing_event is not None:
            structure_event = self._structure.on_swing(swing_event)
            self._liquidity.on_swing(swing_event)
            self._premium_discount.on_swing(swing_event)
            self._ote.on_swing(swing_event)

            if structure_event is not None:
                self._ob.on_structure(structure_event)

        for mitigated_ob in self._ob.newly_mitigated:
            self._breaker.on_ob_mitigated(mitigated_ob)

    def warmup(
        self,
        candles: Iterable[tuple[Decimal, Decimal, Decimal, Decimal]],
    ) -> None:
        """Replay historical OHLC bars (no volume) to warm up detectors."""
        for o, h, l, c in candles:
            self.add_bar(o, h, l, c)

    def reset(self) -> None:
        """Reset all detector state for backtest parameter sweeps."""
        self._swing.reset()
        self._fvg.reset()
        self._structure.reset()
        self._ob.reset()
        self._liquidity.reset()
        self._displacement.reset()
        self._premium_discount.reset()
        self._ote.reset()
        self._vi.reset()
        self._breaker.reset()
        self._bar_idx = 0

    # --- Read-only accessors ---

    @property
    def bar_count(self) -> int:
        return self._bar_idx

    @property
    def swings(self) -> list[SwingEvent]:
        return self._swing.swings

    @property
    def last_swing(self) -> SwingEvent | None:
        return self._swing.last_swing

    @property
    def all_fvgs(self) -> list[FVGEvent]:
        return self._fvg.all_events

    @property
    def active_fvgs(self) -> list[FVGEvent]:
        return self._fvg.active

    @property
    def fvg_bullish_bias(self) -> int:
        return self._fvg.bullish_bias

    @property
    def trend(self) -> int:
        return self._structure.trend

    @property
    def structure_events(self) -> list[StructureEvent]:
        return self._structure.events

    @property
    def last_structure(self) -> StructureEvent | None:
        return self._structure.last_event

    @property
    def all_obs(self) -> list[OrderBlockEvent]:
        return self._ob.all_events

    @property
    def active_obs(self) -> list[OrderBlockEvent]:
        return self._ob.active

    @property
    def all_liquidity(self) -> list[LiquidityPool]:
        return self._liquidity.all_events

    @property
    def active_liquidity(self) -> list[LiquidityPool]:
        return self._liquidity.active

    @property
    def displacement_events(self) -> list[DisplacementEvent]:
        return self._displacement.events

    @property
    def all_vis(self) -> list[VolumeImbalanceEvent]:
        return self._vi.all_events

    @property
    def all_breakers(self) -> list[OrderBlockEvent]:
        return self._breaker.active_breakers

    @property
    def equilibrium(self) -> Decimal:
        return self._premium_discount.equilibrium

    @property
    def fib_levels(self) -> dict[str, Decimal]:
        return self._premium_discount.fib_levels

    def zone_for_price(self, price: Decimal) -> str:
        return self._premium_discount.zone_for_price(price)

    def in_ote_zone(self, price: Decimal) -> bool:
        return self._ote.in_ote_zone(price)

    @property
    def ote_top(self) -> Decimal:
        return self._ote.ote_top

    @property
    def ote_bottom(self) -> Decimal:
        return self._ote.ote_bottom

    @property
    def active_vis(self) -> list[VolumeImbalanceEvent]:
        return self._vi.active

    @property
    def active_breakers(self) -> list[OrderBlockEvent]:
        return self._breaker.active_breakers
