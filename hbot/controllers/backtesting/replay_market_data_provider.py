"""Replay market data provider for shared runtime integration."""
from __future__ import annotations

from typing import Any

from controllers.backtesting.replay_clock import ReplayClock
from controllers.backtesting.types import CandleRow


class ReplayMarketDataProvider:
    def __init__(
        self,
        *,
        clock: ReplayClock,
        connectors: dict[str, Any],
        candles_by_key: dict[tuple[str, str, str], list[CandleRow]],
    ) -> None:
        self._clock = clock
        self._connectors = dict(connectors)
        self._candles_by_key = {
            (str(connector), str(pair), str(interval)): list(candles)
            for (connector, pair, interval), candles in candles_by_key.items()
        }

    def time(self) -> float:
        return self._clock.time()

    def get_connector(self, name: str):
        return self._connectors.get(name)

    def get_candles_df(self, connector: str, pair: str, interval: str, count: int):
        try:
            import pandas as pd  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover
            raise ImportError("pandas is required for replay candle DataFrames") from exc

        candles = self._candles_by_key.get((str(connector), str(pair), str(interval)), [])
        if not candles:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        now_ms = self._clock.now_ms
        visible = [candle for candle in candles if candle.timestamp_ms <= now_ms]
        selected = visible[-max(1, int(count)) :]
        rows = [
            {
                "timestamp": candle.timestamp_ms,
                "open": float(candle.open),
                "high": float(candle.high),
                "low": float(candle.low),
                "close": float(candle.close),
                "volume": float(candle.volume),
            }
            for candle in selected
        ]
        return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])


__all__ = ["ReplayMarketDataProvider"]
