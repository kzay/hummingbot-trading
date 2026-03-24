"""Instrument registry for the PaperDesk service wrapper.

Lazily resolves InstrumentSpec from command metadata, env-var defaults,
or (future) exchange trading rules. Instruments are registered into the
PaperDesk instance before the first order for a given tenant/pair.

Fee/precision defaults are read from env vars at import time so they
can be tuned in docker-compose without code changes.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal

from simulation.types import InstrumentId, InstrumentSpec

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")

# -- Configurable fee defaults (env vars, read once at import) --
_DEFAULT_MAKER_FEE = Decimal(os.getenv("PAPER_EXCHANGE_DEFAULT_MAKER_FEE_PCT", "0.0002"))
_DEFAULT_TAKER_FEE = Decimal(os.getenv("PAPER_EXCHANGE_DEFAULT_TAKER_FEE_PCT", "0.0006"))
_DEFAULT_MIN_NOTIONAL_PERP = Decimal(os.getenv("PAPER_EXCHANGE_DEFAULT_MIN_NOTIONAL_PERP", "5"))
_DEFAULT_MIN_NOTIONAL_SPOT = Decimal(os.getenv("PAPER_EXCHANGE_DEFAULT_MIN_NOTIONAL_SPOT", "1"))

_VENUE_ALIASES: dict[str, str] = {
    "bitget_perpetual": "bitget",
    "bitget_perpetual_paper_trade": "bitget",
    "binance_perpetual": "binance",
    "binance_perpetual_paper_trade": "binance",
    "bybit_perpetual": "bybit",
    "bybit_perpetual_paper_trade": "bybit",
}

_CONNECTOR_IS_PERP: set[str] = {
    "bitget_perpetual",
    "bitget_perpetual_paper_trade",
    "binance_perpetual",
    "binance_perpetual_paper_trade",
    "bybit_perpetual",
    "bybit_perpetual_paper_trade",
}


def _canonical_connector(raw: str) -> str:
    """Strip ``_paper_trade`` suffix and normalize to lowercase."""
    c = str(raw or "").strip().lower()
    if c.endswith("_paper_trade"):
        c = c[:-12]
    return c


def _venue_from_connector(connector_name: str) -> str:
    cn = _canonical_connector(connector_name)
    return _VENUE_ALIASES.get(cn, cn.split("_")[0])


def _instrument_type(connector_name: str) -> str:
    cn = _canonical_connector(connector_name)
    if cn in _CONNECTOR_IS_PERP or "perpetual" in cn or "perp" in cn:
        return "perp"
    return "spot"


def make_instrument_id(connector_name: str, trading_pair: str) -> InstrumentId:
    """Build an InstrumentId from command-level connector/pair strings."""
    pair = str(trading_pair or "").strip().upper()
    return InstrumentId(
        venue=_venue_from_connector(connector_name),
        trading_pair=pair,
        instrument_type=_instrument_type(connector_name),
    )


class InstrumentRegistry:
    """Resolves and caches InstrumentSpec instances.

    Resolution order:
    1. Already-registered spec (cached hit)
    2. Command metadata hints (maker_fee_pct, taker_fee_pct, etc.)
    3. Deterministic defaults for the venue/pair/type
    """

    def __init__(self) -> None:
        self._specs: dict[str, InstrumentSpec] = {}

    def resolve(
        self,
        connector_name: str,
        trading_pair: str,
        metadata: dict[str, str] | None = None,
    ) -> InstrumentSpec:
        """Return a spec, creating one from defaults if needed."""
        iid = make_instrument_id(connector_name, trading_pair)
        key = iid.key
        cached = self._specs.get(key)
        if cached is not None:
            return cached

        spec = self._build_spec(iid, metadata)
        self._specs[key] = spec
        logger.info("InstrumentRegistry: registered %s", key)
        return spec

    def get(self, connector_name: str, trading_pair: str) -> InstrumentSpec | None:
        iid = make_instrument_id(connector_name, trading_pair)
        return self._specs.get(iid.key)

    def _build_spec(
        self,
        iid: InstrumentId,
        metadata: dict[str, str] | None = None,
    ) -> InstrumentSpec:
        md = metadata or {}

        maker_fee = self._dec(md.get("maker_fee_pct"), _DEFAULT_MAKER_FEE)
        taker_fee = self._dec(md.get("taker_fee_pct"), _DEFAULT_TAKER_FEE)

        if iid.is_perp:
            return InstrumentSpec(
                instrument_id=iid,
                price_precision=int(md.get("price_precision", "2")),
                size_precision=int(md.get("size_precision", "4")),
                price_increment=self._dec(md.get("price_increment"), Decimal("0.01")),
                size_increment=self._dec(md.get("size_increment"), Decimal("0.001")),
                min_quantity=self._dec(md.get("min_quantity"), Decimal("0.001")),
                min_notional=self._dec(md.get("min_notional"), _DEFAULT_MIN_NOTIONAL_PERP),
                max_quantity=self._dec(md.get("max_quantity"), Decimal("100")),
                maker_fee_rate=maker_fee,
                taker_fee_rate=taker_fee,
                margin_init=Decimal("0.10"),
                margin_maint=Decimal("0.05"),
                leverage_max=20,
                funding_interval_s=28800,
            )
        return InstrumentSpec(
            instrument_id=iid,
            price_precision=int(md.get("price_precision", "2")),
            size_precision=int(md.get("size_precision", "4")),
            price_increment=self._dec(md.get("price_increment"), Decimal("0.01")),
            size_increment=self._dec(md.get("size_increment"), Decimal("0.0001")),
            min_quantity=self._dec(md.get("min_quantity"), Decimal("0.0001")),
            min_notional=self._dec(md.get("min_notional"), _DEFAULT_MIN_NOTIONAL_SPOT),
            max_quantity=self._dec(md.get("max_quantity"), Decimal("10000")),
            maker_fee_rate=maker_fee,
            taker_fee_rate=taker_fee,
            margin_init=_ZERO,
            margin_maint=_ZERO,
            leverage_max=1,
            funding_interval_s=0,
        )

    @staticmethod
    def _dec(raw: str | None, default: Decimal) -> Decimal:
        if raw is None:
            return default
        try:
            v = Decimal(str(raw))
            return v if v > _ZERO else default
        except Exception:
            return default
