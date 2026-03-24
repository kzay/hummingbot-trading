"""Replay connector facade that matches runtime-adapter expectations."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from controllers.backtesting.historical_feed import HistoricalDataFeed
from controllers.backtesting.replay_clock import ReplayClock
from simulation.portfolio import PaperPortfolio
from simulation.types import InstrumentSpec, PositionAction

_ZERO = Decimal("0")


@dataclass(frozen=True)
class _ReplayBookEntry:
    price: Decimal
    amount: Decimal


class _ReplayOrderBook:
    def __init__(self, bids: list[_ReplayBookEntry], asks: list[_ReplayBookEntry]):
        self._bids = list(bids)
        self._asks = list(asks)

    @property
    def best_bid(self) -> _ReplayBookEntry | None:
        return self._bids[0] if self._bids else None

    @property
    def best_ask(self) -> _ReplayBookEntry | None:
        return self._asks[0] if self._asks else None

    def bid_entries(self):
        return iter(self._bids)

    def ask_entries(self):
        return iter(self._asks)


def _normalize_position_action_hint(position_action: Any) -> PositionAction | None:
    if position_action is None:
        return None
    if isinstance(position_action, PositionAction):
        return position_action
    text = str(getattr(position_action, "name", position_action) or "").strip().lower()
    mapping = {
        "open_long": PositionAction.OPEN_LONG,
        "close_long": PositionAction.CLOSE_LONG,
        "open_short": PositionAction.OPEN_SHORT,
        "close_short": PositionAction.CLOSE_SHORT,
        "auto": PositionAction.AUTO,
    }
    return mapping.get(text)


class ReplayConnector:
    def __init__(
        self,
        *,
        clock: ReplayClock,
        data_feed: HistoricalDataFeed,
        portfolio: PaperPortfolio,
        instrument_spec: InstrumentSpec,
        connector_name: str,
    ) -> None:
        self._clock = clock
        self._data_feed = data_feed
        self._portfolio = portfolio
        self._instrument_spec = instrument_spec
        self._instrument_id = instrument_spec.instrument_id
        self._connector_name = connector_name

    def get_mid_price(self, pair: str | None = None) -> Decimal:
        if pair and str(pair) != self._instrument_id.trading_pair:
            return _ZERO
        return self._data_feed.get_mid_price(self._instrument_id) or _ZERO

    def get_order_book(self, pair: str | None = None) -> _ReplayOrderBook:
        if pair and str(pair) != self._instrument_id.trading_pair:
            return _ReplayOrderBook([], [])
        snapshot = self._data_feed.get_book(self._instrument_id)
        if snapshot is None:
            return _ReplayOrderBook([], [])
        bids = [_ReplayBookEntry(price=level.price, amount=level.size) for level in snapshot.bids]
        asks = [_ReplayBookEntry(price=level.price, amount=level.size) for level in snapshot.asks]
        return _ReplayOrderBook(bids, asks)

    def get_price_by_type(self, pair: str, price_type: Any) -> Decimal:
        name = str(getattr(price_type, "name", price_type) or "").lower()
        book = self.get_order_book(pair)
        if name == "bestbid":
            return book.best_bid.price if book.best_bid is not None else _ZERO
        if name == "bestask":
            return book.best_ask.price if book.best_ask is not None else _ZERO
        if name == "lasttrade":
            return self.get_mid_price(pair)
        return self.get_mid_price(pair)

    def get_funding_info(self, pair: str | None = None) -> SimpleNamespace:
        if pair and str(pair) != self._instrument_id.trading_pair:
            return SimpleNamespace(rate=_ZERO, funding_rate=_ZERO)
        rate = self._data_feed.get_funding_rate(self._instrument_id)
        return SimpleNamespace(rate=rate, funding_rate=rate)

    @property
    def funding_rates(self) -> dict[str, Decimal]:
        rate = self._data_feed.get_funding_rate(self._instrument_id)
        return {self._instrument_id.trading_pair: rate}

    def get_balance(self, asset: str) -> Decimal:
        return self._portfolio.balance(asset)

    def get_available_balance(self, asset: str) -> Decimal:
        return self._portfolio.available(asset)

    def _paper_position_obj(self, position_action: Any = None) -> SimpleNamespace:
        resolved_action = _normalize_position_action_hint(position_action)
        pos = self._portfolio.get_position(self._instrument_id, position_action=resolved_action)
        amount = pos.quantity
        entry_price = pos.avg_entry_price
        if resolved_action in {PositionAction.OPEN_LONG, PositionAction.CLOSE_LONG}:
            amount = pos.long_quantity
            entry_price = pos.long_avg_entry_price
        elif resolved_action in {PositionAction.OPEN_SHORT, PositionAction.CLOSE_SHORT}:
            amount = -pos.short_quantity
            entry_price = pos.short_avg_entry_price
        return SimpleNamespace(
            trading_pair=self._instrument_id.trading_pair,
            amount=amount,
            entry_price=entry_price,
        )

    def get_position(self, trading_pair: str | None = None, *args, **kwargs):
        if trading_pair and str(trading_pair) != self._instrument_id.trading_pair:
            return None
        position_action = kwargs.get("position_action") or kwargs.get("position_side")
        return self._paper_position_obj(position_action)

    def account_positions(self, *args, **kwargs):
        net_pos = self._portfolio.get_position(self._instrument_id)
        return {
            self._instrument_id.trading_pair: {
                "amount": net_pos.quantity,
                "long_amount": net_pos.long_quantity,
                "short_amount": -net_pos.short_quantity,
            }
        }

    @property
    def trading_rules(self) -> dict[str, Any]:
        return {
            self._instrument_id.trading_pair: SimpleNamespace(
                min_order_size=self._instrument_spec.min_quantity,
                min_price_increment=self._instrument_spec.price_increment,
                min_base_amount_increment=self._instrument_spec.size_increment,
                min_notional_size=self._instrument_spec.min_notional,
            )
        }

    @property
    def ready(self) -> bool:
        return True

    @property
    def status_dict(self) -> dict[str, bool]:
        return {"ready": True, "connected": True}


__all__ = ["ReplayConnector"]
