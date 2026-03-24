from __future__ import annotations

from decimal import Decimal

from controllers.backtesting.replay_clock import ReplayClock
from controllers.backtesting.replay_market_reader import ReplayMarketDataReader
from controllers.backtesting.types import TradeRow


def _reader(start_ms: int = 2_500) -> ReplayMarketDataReader:
    clock = ReplayClock(start_ms * 1_000_000)
    trades = [
        TradeRow(timestamp_ms=1_000, side="buy", price=Decimal("100"), size=Decimal("1"), trade_id="t1"),
        TradeRow(timestamp_ms=2_000, side="sell", price=Decimal("99"), size=Decimal("2"), trade_id="t2"),
        TradeRow(timestamp_ms=3_000, side="buy", price=Decimal("101"), size=Decimal("3"), trade_id="t3"),
        TradeRow(timestamp_ms=4_000, side="sell", price=Decimal("98"), size=Decimal("4"), trade_id="t4"),
    ]
    return ReplayMarketDataReader(clock, trades)


class TestReplayMarketReader:
    def test_recent_trades_only_include_visible_window(self):
        reader = _reader(start_ms=2_500)

        trades = reader.recent_trades(count=10)

        assert [trade.trade_id for trade in trades] == ["t1", "t2"]
        assert [trade.exchange_ts_ms for trade in trades] == [1_000, 2_000]

    def test_top_of_book_and_mid_price_use_visible_trades(self):
        reader = _reader(start_ms=4_500)

        top = reader.get_top_of_book()

        assert top is not None
        assert top.best_bid == Decimal("99")
        assert top.best_ask == Decimal("100")
        assert top.best_bid_size == Decimal("2")
        assert top.best_ask_size == Decimal("1")
        assert reader.get_mid_price() == Decimal("99.5")

    def test_depth_imbalance_uses_recent_trade_volumes(self):
        reader = _reader(start_ms=4_500)

        imbalance = reader.get_depth_imbalance(depth=4)

        assert imbalance == Decimal("-0.2")

    def test_trade_flow_features_use_replay_time_for_staleness(self):
        reader = _reader(start_ms=2_500)

        fresh = reader.get_trade_flow_features(count=10, stale_after_ms=1_000)
        reader._clock.advance(3_000_000_000)
        reader.advance(reader._clock.now_ns)
        stale = reader.get_trade_flow_features(count=10, stale_after_ms=1_000)

        assert fresh.trade_count == 2
        assert fresh.buy_volume == Decimal("1")
        assert fresh.sell_volume == Decimal("2")
        assert fresh.delta_volume == Decimal("-1")
        assert fresh.latest_ts_ms == 2_000
        assert fresh.stale is False
        assert stale.stale is True

    def test_no_visible_trades_returns_empty_outputs(self):
        reader = _reader(start_ms=500)

        assert reader.recent_trades() == []
        assert reader.get_top_of_book() is None
        assert reader.get_mid_price() == Decimal("0")
        assert reader.get_trade_flow_features().stale is True

    def test_trade_flow_features_match_golden_fixture(self):
        clock = ReplayClock(55_000 * 1_000_000)
        trades = [
            TradeRow(timestamp_ms=0, side="buy", price=Decimal("100"), size=Decimal("1"), trade_id="g1"),
            TradeRow(timestamp_ms=10_000, side="buy", price=Decimal("101"), size=Decimal("2"), trade_id="g2"),
            TradeRow(timestamp_ms=20_000, side="sell", price=Decimal("100"), size=Decimal("1"), trade_id="g3"),
            TradeRow(timestamp_ms=30_000, side="sell", price=Decimal("99"), size=Decimal("8"), trade_id="g4"),
            TradeRow(timestamp_ms=40_000, side="sell", price=Decimal("98"), size=Decimal("10"), trade_id="g5"),
            TradeRow(timestamp_ms=50_000, side="buy", price=Decimal("101"), size=Decimal("12"), trade_id="g6"),
        ]
        reader = ReplayMarketDataReader(clock, trades)

        features = reader.get_trade_flow_features(
            count=10,
            stale_after_ms=10_000,
            imbalance_threshold=Decimal("2.0"),
            delta_spike_min_baseline=5,
        )

        expected_buy_volume = Decimal("15")
        expected_sell_volume = Decimal("19")
        expected_delta = expected_buy_volume - expected_sell_volume
        expected_imbalance = expected_delta / (expected_buy_volume + expected_sell_volume)
        expected_spike = Decimal("12") / ((Decimal("1") + Decimal("2") + Decimal("1") + Decimal("8") + Decimal("10")) / Decimal("5"))

        assert features.trade_count == 6
        assert features.buy_volume == expected_buy_volume
        assert features.sell_volume == expected_sell_volume
        assert features.delta_volume == expected_delta
        assert features.cvd == expected_delta
        assert features.last_price == Decimal("101")
        assert features.latest_ts_ms == 50_000
        assert features.stale is False
        assert features.imbalance_ratio == expected_imbalance
        assert features.stacked_buy_count == 2
        assert features.stacked_sell_count == 2
        assert features.delta_spike_ratio == expected_spike
