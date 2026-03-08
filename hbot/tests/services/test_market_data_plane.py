from __future__ import annotations

from decimal import Decimal

from services.common import market_data_plane as mdp


def test_directional_trade_features_scores_bullish_divergence(monkeypatch) -> None:
    futures_features = mdp.TradeFlowFeatures(
        trade_count=120,
        buy_volume=Decimal("15"),
        sell_volume=Decimal("6"),
        delta_volume=Decimal("9"),
        cvd=Decimal("8"),
        last_price=Decimal("99"),
        latest_ts_ms=1,
        stale=False,
        imbalance_ratio=Decimal("0.42"),
        stacked_buy_count=4,
        stacked_sell_count=0,
        delta_spike_ratio=Decimal("3.4"),
    )
    spot_features = mdp.TradeFlowFeatures(
        trade_count=120,
        buy_volume=Decimal("18"),
        sell_volume=Decimal("4"),
        delta_volume=Decimal("14"),
        cvd=Decimal("12"),
        last_price=Decimal("100"),
        latest_ts_ms=1,
        stale=False,
        imbalance_ratio=Decimal("0.55"),
        stacked_buy_count=3,
        stacked_sell_count=0,
        delta_spike_ratio=Decimal("1.2"),
    )
    futures_trades = [
        mdp.MarketTrade(price=Decimal("100"), size=Decimal("1"), delta=Decimal("1")),
        mdp.MarketTrade(price=Decimal("99"), size=Decimal("1"), delta=Decimal("1")),
    ]
    spot_trades = [
        mdp.MarketTrade(price=Decimal("100"), size=Decimal("1"), delta=Decimal("1")),
        mdp.MarketTrade(price=Decimal("101"), size=Decimal("1"), delta=Decimal("1")),
    ]

    class FakeSpotReader:
        def __init__(self, *args, **kwargs):
            pass

        def get_trade_flow_features(self, **kwargs):
            return spot_features

        def recent_trades(self, **kwargs):
            return spot_trades

        def _price_change_pct(self, trades):
            return Decimal("0.01")

    reader_cls = mdp.CanonicalMarketDataReader
    reader = object.__new__(reader_cls)
    reader._enabled = False
    reader._stream_scan_count = 50
    reader._stale_after_ms = 15_000
    reader.get_trade_flow_features = lambda **kwargs: futures_features
    reader.recent_trades = lambda **kwargs: futures_trades
    reader.latest_quote = lambda: {"funding_rate": "0.0002"}

    monkeypatch.setattr(mdp, "CanonicalMarketDataReader", FakeSpotReader)
    try:
        result = reader_cls.get_directional_trade_features(
            reader,
            spot_connector_name="bitget",
            spot_trading_pair="BTC-USDT",
            divergence_threshold_pct=Decimal("0.15"),
            stacked_imbalance_min=3,
            delta_spike_threshold=Decimal("3.0"),
            long_funding_max=Decimal("0.0005"),
            short_funding_min=Decimal("-0.0003"),
        )
    finally:
        monkeypatch.setattr(mdp, "CanonicalMarketDataReader", reader_cls)

    assert result.bullish_divergence is True
    assert result.funding_bias == "long"
    assert result.long_score == 9
    assert result.short_score == 0
    assert result.stale is False
