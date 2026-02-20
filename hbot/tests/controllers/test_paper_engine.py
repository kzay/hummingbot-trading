from decimal import Decimal
from types import SimpleNamespace

from controllers.paper_engine import (
    MarketEvent,
    OrderType,
    PaperEngineConfig,
    PaperExecutionAdapter,
)


class _Entry:
    def __init__(self, price: Decimal, amount: Decimal):
        self.price = price
        self.amount = amount


class _Book:
    def __init__(self, bid_p: Decimal, bid_a: Decimal, ask_p: Decimal, ask_a: Decimal):
        self._bids = [_Entry(bid_p, bid_a)]
        self._asks = [_Entry(ask_p, ask_a)]

    def bid_entries(self):
        return self._bids

    def ask_entries(self):
        return self._asks


class _ConnectorStub:
    def __init__(self):
        self.ready = True
        self._balances = {"BTC": Decimal("0.2"), "USDT": Decimal("1000")}
        self.trading_rules = {"BTC-USDT": SimpleNamespace(min_order_size=Decimal("0.0001"))}
        self._book = _Book(Decimal("9999"), Decimal("0.3"), Decimal("10001"), Decimal("0.3"))

    def get_balance(self, asset: str) -> Decimal:
        return self._balances.get(asset, Decimal("0"))

    def get_price_by_type(self, trading_pair: str, price_type):
        name = getattr(price_type, "name", str(price_type))
        if name == "BestBid":
            return Decimal("9999")
        if name == "BestAsk":
            return Decimal("10001")
        return Decimal("10000")

    def get_order_book(self, trading_pair: str):
        return self._book

    def quantize_order_amount(self, trading_pair: str, amount: Decimal) -> Decimal:
        return amount

    def quantize_order_price(self, trading_pair: str, price: Decimal) -> Decimal:
        return price


def test_adapter_exposes_tracker_and_rules():
    paper = _ConnectorStub()
    live = _ConnectorStub()
    adapter = PaperExecutionAdapter(
        connector_name="bitget_paper_trade",
        trading_pair="BTC-USDT",
        paper_connector=paper,
        market_connector=live,
        config=PaperEngineConfig(),
        time_fn=lambda: 1_700_000_000.0,
    )
    assert hasattr(adapter, "_order_tracker")
    assert "BTC-USDT" in adapter.trading_rules


def test_limit_order_produces_created_and_filled_events():
    events = []
    paper = _ConnectorStub()
    live = _ConnectorStub()
    adapter = PaperExecutionAdapter(
        connector_name="bitget_paper_trade",
        trading_pair="BTC-USDT",
        paper_connector=paper,
        market_connector=live,
        config=PaperEngineConfig(),
        time_fn=lambda: 1_700_000_100.0,
    )

    adapter.add_listener(MarketEvent.BuyOrderCreated, lambda *_: events.append("created"))
    adapter.add_listener(MarketEvent.OrderFilled, lambda *_: events.append("filled"))
    adapter.add_listener(MarketEvent.BuyOrderCompleted, lambda *_: events.append("completed"))

    order_id = adapter.buy(
        trading_pair="BTC-USDT",
        amount=Decimal("0.01"),
        order_type=OrderType.LIMIT,
        price=Decimal("10005"),
    )
    tracked = adapter._order_tracker.fetch_order(order_id)
    assert tracked is not None
    assert tracked.executed_amount_base > 0
    assert "created" in events
    assert "filled" in events


def test_cancel_releases_reserved_balance():
    paper = _ConnectorStub()
    live = _ConnectorStub()
    adapter = PaperExecutionAdapter(
        connector_name="bitget_paper_trade",
        trading_pair="BTC-USDT",
        paper_connector=paper,
        market_connector=live,
        config=PaperEngineConfig(),
        time_fn=lambda: 1_700_000_200.0,
    )
    order_id = adapter.sell(
        trading_pair="BTC-USDT",
        amount=Decimal("0.02"),
        order_type=OrderType.LIMIT_MAKER,
        price=Decimal("10050"),
    )
    tracked = adapter._order_tracker.fetch_order(order_id)
    assert tracked is not None
    assert adapter.get_available_balance("BTC") < adapter.get_balance("BTC")
    assert adapter.cancel("BTC-USDT", order_id)
    assert adapter.get_available_balance("BTC") == adapter.get_balance("BTC")
    assert tracked.current_state == "CANCELED"


def test_insufficient_balance_emits_failure():
    paper = _ConnectorStub()
    live = _ConnectorStub()
    adapter = PaperExecutionAdapter(
        connector_name="bitget_paper_trade",
        trading_pair="BTC-USDT",
        paper_connector=paper,
        market_connector=live,
        config=PaperEngineConfig(),
        time_fn=lambda: 1_700_000_300.0,
    )
    failures = []
    adapter.add_listener(MarketEvent.OrderFailure, lambda *_: failures.append(1))
    adapter.buy(
        trading_pair="BTC-USDT",
        amount=Decimal("10"),  # way beyond quote balance
        order_type=OrderType.LIMIT,
        price=Decimal("10000"),
    )
    assert failures
    assert adapter.paper_stats["paper_reject_count"] > 0
