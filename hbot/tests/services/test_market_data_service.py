from __future__ import annotations

from services.common.canonical_market_state import parse_canonical_market_state
from services.market_data_service.main import (
    MarketSubscription,
    _build_binance_depth_event,
    _build_binance_quote_event,
    _build_binance_trade_event,
    _build_bitget_depth_event,
    _build_bitget_quote_event,
    _build_bitget_trade_events,
    _parse_subscriptions,
)


def test_parse_subscriptions_handles_connector_pair_list() -> None:
    subscriptions = _parse_subscriptions("bitget_perpetual|BTC-USDT, binance_perpetual_testnet|ethusdt")
    assert subscriptions == [
        MarketSubscription(connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
        MarketSubscription(connector_name="binance_perpetual_testnet", trading_pair="ETH-USDT"),
    ]


def test_build_bitget_quote_event_from_ticker_message() -> None:
    event = _build_bitget_quote_event(
        {
            "arg": {"channel": "ticker", "instId": "BTCUSDT"},
            "data": [
                {
                    "instId": "BTCUSDT",
                    "bidPr": "100.0",
                    "askPr": "100.2",
                    "bidSz": "1.5",
                    "askSz": "1.7",
                    "lastPr": "100.1",
                    "fundingRate": "0.0001",
                    "ts": "1741200000000",
                }
            ],
        },
        MarketSubscription(connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
    )
    assert event is not None
    assert event.connector_name == "bitget_perpetual"
    assert event.best_bid == 100.0
    assert event.best_ask == 100.2
    assert event.mid_price == 100.1
    assert event.venue_symbol == "BTCUSDT"


def test_build_binance_quote_event_from_book_ticker_message() -> None:
    event = _build_binance_quote_event(
        {
            "u": 400900217,
            "s": "BTCUSDT",
            "b": "100.0",
            "B": "2.0",
            "a": "100.2",
            "A": "1.0",
            "E": 1741200000000,
        },
        MarketSubscription(connector_name="binance_perpetual_testnet", trading_pair="BTC-USDT"),
    )
    assert event is not None
    assert event.connector_name == "binance_perpetual_testnet"
    assert event.best_bid == 100.0
    assert event.best_ask == 100.2
    assert event.market_sequence == 400900217


def test_build_bitget_trade_events_from_trade_message() -> None:
    events = _build_bitget_trade_events(
        {
            "arg": {"channel": "trade", "instId": "BTCUSDT"},
            "data": [
                {
                    "tradeId": "101",
                    "side": "buy",
                    "px": "100.1",
                    "sz": "0.25",
                    "ts": "1741200000001",
                },
                {
                    "tradeId": "102",
                    "side": "sell",
                    "px": "100.0",
                    "sz": "0.40",
                    "ts": "1741200000002",
                },
            ],
        },
        MarketSubscription(connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
    )
    assert len(events) == 2
    assert events[0].side == "buy"
    assert events[0].price == 100.1
    assert events[0].size == 0.25
    assert events[0].extra["aggressor_side"] == "buy"
    assert events[1].side == "sell"


def test_build_binance_trade_event_from_trade_message() -> None:
    event = _build_binance_trade_event(
        {
            "e": "trade",
            "E": 1741200000000,
            "s": "BTCUSDT",
            "t": 555,
            "p": "100.3",
            "q": "0.15",
            "T": 1741200000001,
            "m": True,
        },
        MarketSubscription(connector_name="binance_perpetual_testnet", trading_pair="BTC-USDT"),
    )
    assert event is not None
    assert event.side == "sell"
    assert event.price == 100.3
    assert event.size == 0.15
    assert event.extra["buyer_is_maker"] == "1"
    assert event.extra["aggressor_side"] == "sell"


def test_build_bitget_depth_event_from_books_message() -> None:
    event = _build_bitget_depth_event(
        {
            "arg": {"channel": "books15", "instId": "BTCUSDT"},
            "data": [
                {
                    "ts": "1741200000000",
                    "bids": [["100.0", "2.5"], ["99.9", "1.0"]],
                    "asks": [["100.2", "1.5"], ["100.3", "1.0"]],
                }
            ],
        },
        MarketSubscription(connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
        depth_levels=2,
    )
    assert event is not None
    assert event.connector_name == "bitget_perpetual"
    assert event.best_bid == 100.0
    assert event.best_ask == 100.2
    assert len(event.bids) == 2
    assert len(event.asks) == 2


def test_build_binance_depth_event_from_depth_message() -> None:
    event = _build_binance_depth_event(
        {
            "u": 400900217,
            "E": 1741200000000,
            "b": [["100.0", "3.0"], ["99.9", "1.0"]],
            "a": [["100.2", "2.0"], ["100.3", "1.0"]],
        },
        MarketSubscription(connector_name="binance_perpetual_testnet", trading_pair="BTC-USDT"),
        depth_levels=2,
    )
    assert event is not None
    assert event.connector_name == "binance_perpetual_testnet"
    assert event.best_bid == 100.0
    assert event.best_ask == 100.2
    assert event.market_sequence == 400900217


def test_parse_canonical_market_state_accepts_depth_levels_as_lists() -> None:
    state = parse_canonical_market_state(
        {
            "event_type": "market_depth_snapshot",
            "event_id": "depth-1",
            "connector_name": "bitget_perpetual",
            "trading_pair": "BTC-USDT",
            "timestamp_ms": 1_741_200_000_000,
            "market_sequence": 123,
            "bids": [["100.0", "3.0"], ["99.9", "1.0"]],
            "asks": [["100.2", "2.0"], ["100.3", "1.0"]],
        }
    )
    assert state is not None
    assert float(state.best_bid) == 100.0
    assert float(state.best_ask) == 100.2
    assert float(state.best_bid_size) == 3.0
    assert float(state.best_ask_size) == 2.0
