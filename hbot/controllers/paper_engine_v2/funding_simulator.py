"""Funding rate simulator for perpetual instruments.

Follows NautilusTrader SimulationModule pattern (like FXRolloverInterestConfig).
Applies periodic funding charges to open perp positions every funding_interval_s.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict, List, Tuple

from controllers.paper_engine_v2.types import (
    FundingApplied,
    InstrumentSpec,
    _ZERO,
    _uuid,
)

logger = logging.getLogger(__name__)


class FundingSimulator:
    """Applies periodic funding charges to open perp positions.

    The funding rate is sourced from the MarketDataFeed on each tick.
    A positive funding rate means longs pay shorts; we model this as a debit
    on any open position (simplified: sign of rate does not affect direction here,
    consistent with 'cost' model for desk risk purposes).
    """

    def __init__(self) -> None:
        self._last_funding_ns: Dict[str, int] = {}

    def tick(
        self,
        now_ns: int,
        portfolio: "PaperPortfolio",  # type: ignore[name-defined]  # noqa: F821
        instruments: Dict[str, Tuple[InstrumentSpec, Decimal]],  # key → (spec, funding_rate)
    ) -> List[FundingApplied]:
        events: List[FundingApplied] = []
        for key, (spec, funding_rate) in instruments.items():
            if not spec.instrument_id.is_perp or spec.funding_interval_s <= 0:
                continue
            if funding_rate == _ZERO:
                continue

            interval_ns = spec.funding_interval_s * 1_000_000_000
            last_ns = self._last_funding_ns.get(key, -1)
            if last_ns < 0:
                # First call: set baseline, do not charge yet
                self._last_funding_ns[key] = now_ns
                continue
            if (now_ns - last_ns) < interval_ns:
                continue

            self._last_funding_ns[key] = now_ns
            pos = portfolio.get_position(spec.instrument_id)
            if pos.abs_quantity <= _ZERO:
                continue

            notional = pos.abs_quantity * pos.avg_entry_price
            charge = abs(funding_rate) * notional

            try:
                event = portfolio.apply_funding(spec.instrument_id, charge, now_ns)
                # Enrich with actual funding rate
                import dataclasses
                event = dataclasses.replace(event, funding_rate=funding_rate)
                events.append(event)
                logger.debug(
                    "Funding applied: %s rate=%s charge=%s notional=%s",
                    key, funding_rate, charge, notional,
                )
            except Exception as exc:
                logger.error("Funding apply failed for %s: %s", key, exc, exc_info=True)

        return events

    def reset(self) -> None:
        """Reset all funding timestamps (e.g., on daily rollover)."""
        self._last_funding_ns.clear()
