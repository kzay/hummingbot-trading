from __future__ import annotations

from services.common.canonical_market_state import parse_canonical_market_state
from services.market_data_service.main import (
    MarketDataServiceConfig,
    MarketSubscription,
    _AdapterThread,
    _build_binance_depth_event,
    _build_binance_quote_event,
    _build_binance_trade_event,
    _build_bitget_depth_event,
    _build_bitget_quote_event,
    _build_bitget_trade_events,
    _discover_subscriptions_from_controller_configs,
    _parse_subscriptions,
    _resolve_subscriptions,
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
    assert event.market_sequence is None


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
    assert event.market_sequence is None


def test_build_bitget_quote_event_uses_explicit_sequence_when_present() -> None:
    event = _build_bitget_quote_event(
        {
            "arg": {"channel": "ticker", "instId": "BTCUSDT"},
            "data": [
                {
                    "instId": "BTCUSDT",
                    "bidPr": "100.0",
                    "askPr": "100.2",
                    "lastPr": "100.1",
                    "ts": "1741200000000",
                    "seq": "321",
                }
            ],
        },
        MarketSubscription(connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
    )
    assert event is not None
    assert event.market_sequence == 321


def test_build_bitget_depth_event_uses_explicit_sequence_when_present() -> None:
    event = _build_bitget_depth_event(
        {
            "arg": {"channel": "books15", "instId": "BTCUSDT"},
            "data": [
                {
                    "ts": "1741200000000",
                    "sequence": "654",
                    "bids": [["100.0", "2.5"]],
                    "asks": [["100.2", "1.5"]],
                }
            ],
        },
        MarketSubscription(connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
        depth_levels=2,
    )
    assert event is not None
    assert event.market_sequence == 654


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


class _DummyAdapter(_AdapterThread):
    def _run_ws(self) -> None:
        raise NotImplementedError


def test_depth_publish_throttle_allows_first_changed_and_forced_refresh() -> None:
    cfg = MarketDataServiceConfig(
        enabled=True,
        subscriptions=[],
        depth_publish_min_interval_ms=250,
        depth_publish_force_interval_ms=1000,
    )
    adapter = _DummyAdapter(
        subscription=MarketSubscription(connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
        cfg=cfg,
        publisher=object(),  # type: ignore[arg-type]
    )

    first_key = (100.0, 100.2, 1.0, 1.5)
    changed_key = (100.1, 100.3, 1.1, 1.4)

    assert adapter._should_publish_depth(first_key, now_ms=1_000) is True
    adapter._last_depth_ms = 1_000
    adapter._last_depth_publish_key = first_key
    assert adapter._should_publish_depth(first_key, now_ms=1_100) is False
    assert adapter._should_publish_depth(changed_key, now_ms=1_100) is False
    assert adapter._should_publish_depth(changed_key, now_ms=1_260) is True
    assert adapter._should_publish_depth(first_key, now_ms=2_100) is True


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


def test_discover_subscriptions_from_controller_configs_dedupes_and_canonicalizes(tmp_path) -> None:
    bot1 = tmp_path / "bot1" / "conf" / "controllers"
    bot1.mkdir(parents=True)
    (bot1 / "a.yml").write_text("connector_name: bitget_perpetual\ntrading_pair: BTC-USDT\n", encoding="utf-8")
    (bot1 / "b.yml").write_text("connector_name: bitget_paper_trade\ntrading_pair: btc_usdt\n", encoding="utf-8")
    bot2 = tmp_path / "bot2" / "conf" / "controllers"
    bot2.mkdir(parents=True)
    (bot2 / "c.yml").write_text("connector_name: bitget_perpetual\ntrading_pair: ETH-USDT\n", encoding="utf-8")

    subscriptions = _discover_subscriptions_from_controller_configs(tmp_path)

    assert subscriptions == [
        MarketSubscription(connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
        MarketSubscription(connector_name="bitget_perpetual", trading_pair="ETH-USDT"),
    ]


def test_resolve_subscriptions_merges_manual_and_discovered(monkeypatch, tmp_path) -> None:
    bot1 = tmp_path / "bot1" / "conf" / "controllers"
    bot1.mkdir(parents=True)
    (bot1 / "a.yml").write_text("connector_name: bitget_perpetual\ntrading_pair: ETH-USDT\n", encoding="utf-8")

    monkeypatch.setenv("MARKET_DATA_SERVICE_SUBSCRIPTIONS", "bitget_perpetual|BTC-USDT")
    monkeypatch.setenv("MARKET_DATA_SERVICE_AUTO_DISCOVER", "true")
    monkeypatch.setenv("MARKET_DATA_SERVICE_CONTROLLER_CONFIG_ROOT", str(tmp_path))

    subscriptions = _resolve_subscriptions()

    assert subscriptions == [
        MarketSubscription(connector_name="bitget_perpetual", trading_pair="BTC-USDT"),
        MarketSubscription(connector_name="bitget_perpetual", trading_pair="ETH-USDT"),
    ]


def test_resolve_subscriptions_filters_discovered_connectors(monkeypatch, tmp_path) -> None:
    bot1 = tmp_path / "bot1" / "conf" / "controllers"
    bot1.mkdir(parents=True)
    (bot1 / "a.yml").write_text("connector_name: bitget_perpetual\ntrading_pair: ETH-USDT\n", encoding="utf-8")
    (bot1 / "b.yml").write_text("connector_name: binance_perpetual_testnet\ntrading_pair: BTC-USDT\n", encoding="utf-8")

    monkeypatch.setenv("MARKET_DATA_SERVICE_SUBSCRIPTIONS", "")
    monkeypatch.setenv("MARKET_DATA_SERVICE_AUTO_DISCOVER", "true")
    monkeypatch.setenv("MARKET_DATA_SERVICE_CONTROLLER_CONFIG_ROOT", str(tmp_path))
    monkeypatch.setenv("MARKET_DATA_SERVICE_DISCOVERY_CONNECTORS", "bitget_perpetual")

    subscriptions = _resolve_subscriptions()

    assert subscriptions == [
        MarketSubscription(connector_name="bitget_perpetual", trading_pair="ETH-USDT"),
    ]
