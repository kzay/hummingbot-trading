"""Backtesting engine for strategy simulation against historical market data.

Reuses Paper Engine V2 (PaperDesk, matching engine, fill models, portfolio)
with historical data feeds to provide fill-model parity between backtest
and paper trading.

The backtesting package is self-contained.  No imports from the production
runtime (controllers.runtime.*, controllers.price_buffer, etc.) are
required.  The optional ``runtime_adapter`` module bridges to production
components for parity testing when those modules are available.

Public API:
    - BacktestHarness / DeskFactory: Core time-stepping loop and desk creation
    - BacktestConfig / BacktestResult: Configuration and result types
    - BacktestTickAdapter: Protocol any adapter must satisfy
    - SimpleBacktestAdapter: Self-contained adapter (default, no runtime deps)
    - HistoricalDataFeed: MarketDataFeed implementation for historical data
    - CandleBookSynthesizer: Converts OHLCV candles to OrderBookSnapshot
    - SweepRunner / WalkForwardRunner: Parameter search and walk-forward validation
    - save_json_report / print_summary: Reporting utilities
"""
from controllers.backtesting.book_synthesizer import CandleBookSynthesizer
from controllers.backtesting.harness import BacktestHarness, DeskFactory
from controllers.backtesting.hb_stubs import install_hb_stubs
from controllers.backtesting.historical_feed import HistoricalDataFeed
from controllers.backtesting.pullback_adapter import BacktestPullbackAdapter
from controllers.backtesting.replay_clock import ReplayClock
from controllers.backtesting.replay_connector import ReplayConnector
from controllers.backtesting.replay_injection import ReplayInjection
from controllers.backtesting.replay_market_data_provider import ReplayMarketDataProvider
from controllers.backtesting.replay_market_reader import ReplayMarketDataReader
from controllers.backtesting.report import print_summary, save_json_report
from controllers.backtesting.simple_adapter import SimpleBacktestAdapter
from controllers.backtesting.sweep import SweepRunner
from controllers.backtesting.types import (
    BacktestConfig,
    BacktestResult,
    BacktestTickAdapter,
    CandleRow,
    FundingRow,
    SweepConfig,
    SweepResult,
    TradeRow,
    WalkForwardConfig,
    WalkForwardResult,
)
from controllers.backtesting.walkforward import WalkForwardRunner

_LAZY_REPLAY_EXPORTS = {
    "ReplayConfig",
    "ReplayDataConfig",
    "ReplayHarness",
    "ReplayPreparedContext",
    "load_replay_config",
}


def __getattr__(name):
    if name in _LAZY_REPLAY_EXPORTS:
        from controllers.backtesting import replay_harness as _replay_harness

        return getattr(_replay_harness, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "BacktestConfig",
    "BacktestHarness",
    "BacktestPullbackAdapter",
    "BacktestResult",
    "BacktestTickAdapter",
    "CandleBookSynthesizer",
    "CandleRow",
    "DeskFactory",
    "FundingRow",
    "HistoricalDataFeed",
    "ReplayClock",
    "ReplayConfig",
    "ReplayConnector",
    "ReplayDataConfig",
    "ReplayHarness",
    "ReplayInjection",
    "ReplayMarketDataProvider",
    "ReplayMarketDataReader",
    "ReplayPreparedContext",
    "SimpleBacktestAdapter",
    "SweepConfig",
    "SweepResult",
    "SweepRunner",
    "TradeRow",
    "WalkForwardConfig",
    "WalkForwardResult",
    "WalkForwardRunner",
    "install_hb_stubs",
    "load_replay_config",
    "print_summary",
    "save_json_report",
]
