from __future__ import annotations

import sys
import types

from platform_lib.market_data.ccxt_ohlcv_bar_reader import ccxt_rest_bar_reader
from platform_lib.market_data.market_history_types import MarketBarKey


def test_ccxt_reader_respects_disabled_env(monkeypatch) -> None:
    monkeypatch.setenv("HB_HISTORY_CCXT_ENABLED", "false")
    out = ccxt_rest_bar_reader(
        MarketBarKey("bitget_perpetual", "BTC-USDT", "quote_mid"),
        bar_interval_s=60,
        limit=5,
        end_time_ms=300_000,
        require_closed=True,
    )
    assert out == []


def test_ccxt_reader_only_supports_1m_interval(monkeypatch) -> None:
    monkeypatch.setenv("HB_HISTORY_CCXT_ENABLED", "true")
    out = ccxt_rest_bar_reader(
        MarketBarKey("bitget_perpetual", "BTC-USDT", "quote_mid"),
        bar_interval_s=900,
        limit=5,
        end_time_ms=300_000,
        require_closed=True,
    )
    assert out == []


def test_ccxt_reader_uses_fetch_ohlcv(monkeypatch) -> None:
    monkeypatch.setenv("HB_HISTORY_CCXT_ENABLED", "true")

    class _Ex:
        def __init__(self, _opts=None) -> None:
            self.markets: dict[str, object] = {}

        def load_markets(self) -> None:
            self.markets = {"BTC/USDT:USDT": {}}

        def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
            assert timeframe == "1m"
            assert symbol == "BTC/USDT:USDT"
            t0 = 60_000
            return [
                [t0, 100.0, 101.0, 99.0, 100.0, 10.0],
                [t0 + 60_000, 100.0, 102.0, 100.0, 101.0, 10.0],
            ]

    fake_ccxt = types.SimpleNamespace(bitget=_Ex)
    monkeypatch.setitem(sys.modules, "ccxt", fake_ccxt)

    out = ccxt_rest_bar_reader(
        MarketBarKey("bitget_perpetual", "BTC-USDT", "quote_mid"),
        bar_interval_s=60,
        limit=5,
        end_time_ms=600_000,
        require_closed=True,
    )
    assert len(out) == 2
    assert int(out[0].bucket_start_ms) == 60_000
    assert out[0].bar_source == "exchange_ohlcv"
