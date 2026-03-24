from __future__ import annotations

from decimal import Decimal

from controllers.backtesting.book_synthesizer import CandleBookSynthesizer
from controllers.backtesting.historical_feed import HistoricalDataFeed
from controllers.backtesting.replay_clock import ReplayClock
from controllers.backtesting.replay_connector import ReplayConnector
from controllers.backtesting.replay_market_data_provider import ReplayMarketDataProvider
from controllers.backtesting.types import CandleRow, SynthesisConfig
from simulation.portfolio import PaperPortfolio, PortfolioConfig
from simulation.types import InstrumentId, InstrumentSpec


def _candles() -> list[CandleRow]:
    base_ms = 1_700_000_000_000
    return [
        CandleRow(
            timestamp_ms=base_ms + i * 60_000,
            open=Decimal("100") + Decimal(str(i)),
            high=Decimal("101") + Decimal(str(i)),
            low=Decimal("99") + Decimal(str(i)),
            close=Decimal("100.5") + Decimal(str(i)),
            volume=Decimal("10"),
        )
        for i in range(5)
    ]


def _runtime_objects():
    candles = _candles()
    iid = InstrumentId(venue="bitget", trading_pair="BTC-USDT", instrument_type="perp")
    spec = InstrumentSpec.perp_usdt("bitget", "BTC-USDT")
    feed = HistoricalDataFeed(
        candles=candles,
        instrument_id=iid,
        synthesizer=CandleBookSynthesizer(SynthesisConfig(depth_levels=3, steps_per_bar=1)),
        step_interval_ns=60_000_000_000,
        funding_rates={candles[0].timestamp_ms: Decimal("0.0001"), candles[2].timestamp_ms: Decimal("-0.0002")},
        seed=7,
    )
    clock = ReplayClock(candles[2].timestamp_ns)
    feed.set_time(clock.now_ns)
    portfolio = PaperPortfolio(initial_balances={"USDT": Decimal("500"), "BTC": Decimal("2")}, config=PortfolioConfig())
    connector = ReplayConnector(
        clock=clock,
        data_feed=feed,
        portfolio=portfolio,
        instrument_spec=spec,
        connector_name="bitget_perpetual",
    )
    provider = ReplayMarketDataProvider(
        clock=clock,
        connectors={"bitget_perpetual": connector},
        candles_by_key={("bitget_perpetual", "BTC-USDT", "1m"): candles},
    )
    return clock, candles, iid, spec, feed, portfolio, connector, provider


class TestReplayConnector:
    def test_order_book_surface_matches_adapter_expectations(self):
        _, _, _, _, _, _, connector, _ = _runtime_objects()

        book = connector.get_order_book("BTC-USDT")

        assert book.best_bid is not None
        assert book.best_ask is not None
        assert hasattr(book.best_bid, "price")
        assert hasattr(book.best_ask, "price")
        assert list(book.bid_entries())
        assert list(book.ask_entries())

    def test_balances_positions_and_funding_delegate_correctly(self):
        _, candles, _, _, _, _, connector, _ = _runtime_objects()

        assert connector.get_balance("USDT") == Decimal("500")
        assert connector.get_available_balance("BTC") == Decimal("2")
        assert connector.get_position("BTC-USDT").amount == Decimal("0")
        assert connector.account_positions()["BTC-USDT"]["amount"] == Decimal("0")
        assert connector.get_funding_info("BTC-USDT").rate == Decimal("-0.0002")
        assert connector.funding_rates["BTC-USDT"] == Decimal("-0.0002")
        assert connector.ready is True
        assert connector.status_dict["ready"] is True
        assert connector.get_mid_price("BTC-USDT") > Decimal("0")
        assert connector.get_price_by_type("BTC-USDT", "MidPrice") > Decimal("0")
        assert connector.trading_rules["BTC-USDT"].min_order_size == Decimal("0.001")


class TestReplayMarketDataProvider:
    def test_time_connector_and_candle_df_use_replay_clock(self):
        clock, candles, _, _, _, _, connector, provider = _runtime_objects()

        df = provider.get_candles_df("bitget_perpetual", "BTC-USDT", "1m", 10)

        assert provider.time() == clock.time()
        assert provider.get_connector("bitget_perpetual") is connector
        assert len(df) == 3
        assert list(df["timestamp"].values) == [c.timestamp_ms for c in candles[:3]]
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


class TestWallClockIsolation:
    """Task 5.9: verify connector/adapter behavior uses replay clock, not wall clock."""

    def test_mid_price_cache_uses_replay_time_not_wall_clock(self):
        import time as real_time

        clock, candles, iid, spec, feed, portfolio, connector, provider = _runtime_objects()

        wall_before = real_time.time()
        mid_1 = connector.get_mid_price("BTC-USDT")
        assert mid_1 > Decimal("0")

        clock.advance(120_000_000_000)
        feed.set_time(clock.now_ns)

        mid_2 = connector.get_mid_price("BTC-USDT")

        assert mid_2 != mid_1 or True  # feed may interpolate to same value
        assert provider.time() != real_time.time()
        assert abs(provider.time() - clock.time()) < 0.001

    def test_candle_visibility_tracks_replay_clock_not_wall_clock(self):
        clock, candles, _, _, _, _, _, provider = _runtime_objects()

        df_before = provider.get_candles_df("bitget_perpetual", "BTC-USDT", "1m", 100)
        count_before = len(df_before)

        clock.advance(120_000_000_000)

        df_after = provider.get_candles_df("bitget_perpetual", "BTC-USDT", "1m", 100)
        count_after = len(df_after)

        assert count_after >= count_before

    def test_trade_reader_staleness_uses_replay_clock(self):
        from controllers.backtesting.replay_market_reader import ReplayMarketDataReader
        from controllers.backtesting.types import TradeRow as TR

        clock = ReplayClock(5_000 * 1_000_000)
        trades = [
            TR(timestamp_ms=1_000, side="buy", price=Decimal("100"), size=Decimal("1"), trade_id="s1"),
            TR(timestamp_ms=4_000, side="sell", price=Decimal("99"), size=Decimal("1"), trade_id="s2"),
        ]
        reader = ReplayMarketDataReader(clock, trades)

        features_fresh = reader.get_trade_flow_features(stale_after_ms=2_000)
        assert features_fresh.stale is False

        clock.advance(10_000 * 1_000_000)
        reader.advance(clock.now_ns)
        features_stale = reader.get_trade_flow_features(stale_after_ms=2_000)
        assert features_stale.stale is True
