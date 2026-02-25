"""Fee models for Paper Engine v2.

Three implementations following NautilusTrader conventions:
- MakerTakerFeeModel: instrument-defined rates
- TieredFeeModel: reads config/fee_profiles.json
- FixedFeeModel: flat commission
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Protocol

from controllers.paper_engine_v2.types import InstrumentSpec

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class FeeModel(Protocol):
    def compute(self, notional: Decimal, is_maker: bool) -> Decimal:
        """Return the fee in quote asset for this fill. Does NOT affect PnL."""
        ...


# ---------------------------------------------------------------------------
# MakerTakerFeeModel (default)
# ---------------------------------------------------------------------------

class MakerTakerFeeModel:
    """Uses rates from InstrumentSpec (loaded from exchange or fee_profiles.json)."""

    def __init__(self, maker_rate: Decimal, taker_rate: Decimal):
        self._maker = maker_rate
        self._taker = taker_rate

    def compute(self, notional: Decimal, is_maker: bool) -> Decimal:
        rate = self._maker if is_maker else self._taker
        return max(_ZERO, notional * rate)

    @classmethod
    def from_spec(cls, spec: InstrumentSpec) -> "MakerTakerFeeModel":
        return cls(maker_rate=spec.maker_fee_rate, taker_rate=spec.taker_fee_rate)


# ---------------------------------------------------------------------------
# TieredFeeModel
# ---------------------------------------------------------------------------

_PROFILES_CACHE: Optional[Dict] = None


def _load_fee_profiles(profiles_path: str) -> Dict:
    global _PROFILES_CACHE
    if _PROFILES_CACHE is not None:
        return _PROFILES_CACHE
    try:
        path = Path(profiles_path)
        if not path.is_absolute():
            # Try relative to hbot root
            hbot_root = Path(__file__).parent.parent.parent
            path = hbot_root / profiles_path
        _PROFILES_CACHE = json.loads(path.read_text(encoding="utf-8"))
        logger.debug("Loaded fee profiles from %s", path)
        return _PROFILES_CACHE
    except Exception as exc:
        logger.warning("Could not load fee profiles from %s: %s", profiles_path, exc)
        return {}


class TieredFeeModel:
    """Reads maker/taker rates from config/fee_profiles.json."""

    def __init__(
        self,
        venue: str,
        profile: str = "vip0",
        profiles_path: str = "config/fee_profiles.json",
    ):
        data = _load_fee_profiles(profiles_path)
        rates: Dict = {}
        try:
            rates = data["profiles"][profile][venue]
        except (KeyError, TypeError):
            logger.warning(
                "Fee profile not found: profile=%s venue=%s -- using defaults 0.001/0.001",
                profile, venue,
            )
        self._maker = Decimal(str(rates.get("maker", "0.001")))
        self._taker = Decimal(str(rates.get("taker", "0.001")))

    def compute(self, notional: Decimal, is_maker: bool) -> Decimal:
        rate = self._maker if is_maker else self._taker
        return max(_ZERO, notional * rate)


# ---------------------------------------------------------------------------
# FixedFeeModel
# ---------------------------------------------------------------------------

class FixedFeeModel:
    """Flat commission per fill (Nautilus FixedFeeModel equivalent)."""

    def __init__(self, commission: Decimal):
        self._commission = max(_ZERO, commission)

    def compute(self, notional: Decimal, is_maker: bool) -> Decimal:
        return self._commission


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_fee_model(
    source: str,
    spec: InstrumentSpec,
    profile: str = "vip0",
    profiles_path: str = "config/fee_profiles.json",
) -> FeeModel:
    """Create a fee model by source name."""
    if source == "fee_profiles":
        return TieredFeeModel(
            venue=spec.instrument_id.venue,
            profile=profile,
            profiles_path=profiles_path,
        )
    return MakerTakerFeeModel.from_spec(spec)
