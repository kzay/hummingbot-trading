"""Backtest runner — wires data provider, strategy adapter, fill simulator,
portfolio tracker, and report writer into a single execution pipeline.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional

from scripts.backtest.harness.data_provider import MarketDataProvider
from scripts.backtest.harness.fill_simulator import FillSimulator
from scripts.backtest.harness.portfolio_tracker import PortfolioTracker
from scripts.backtest.harness.report_writer import write_bars, write_summary
from scripts.backtest.harness.strategy_adapter import BacktestState, StrategyAdapter


class BacktestRunner:
    """Orchestrates a single backtest run.

    Usage::

        runner = BacktestRunner(
            data_provider=EventStoreProvider(path),
            strategy=EppV24Adapter(config),
            fill_sim=FillSimulator(...),
            portfolio=PortfolioTracker(initial_base, initial_quote),
        )
        result = runner.run(output_dir=Path("reports/backtest/runs"))
    """

    def __init__(
        self,
        data_provider: MarketDataProvider,
        strategy: StrategyAdapter,
        fill_sim: FillSimulator,
        portfolio: PortfolioTracker,
        venue: str = "",
        trading_pair: str = "",
        config_hash: str = "",
    ):
        self._data = data_provider
        self._strategy = strategy
        self._fill_sim = fill_sim
        self._portfolio = portfolio
        self._venue = venue
        self._pair = trading_pair
        self._config_hash = config_hash

    def run(self, output_dir: Optional[Path] = None) -> Dict[str, object]:
        """Execute the backtest and write reports.

        Returns the summary dict.
        """
        run_id = uuid.uuid4().hex[:12]
        state = BacktestState(
            base_balance=self._portfolio.base_balance,
            quote_balance=self._portfolio.quote_balance,
        )

        start_ts = 0.0
        end_ts = 0.0

        for bar in self._data.bars():
            if start_ts == 0.0:
                start_ts = bar.timestamp_s
            end_ts = bar.timestamp_s
            state.bar_index += 1

            intents = self._strategy.process_bar(bar, state)

            for intent in intents:
                fill = self._fill_sim.evaluate(intent, bar)
                if fill is not None:
                    self._portfolio.apply_fill(fill)

            snap = self._portfolio.snapshot(bar.timestamp_s, bar.mid_price)
            state.equity_quote = snap.equity_quote
            state.base_balance = snap.base_balance
            state.quote_balance = snap.quote_balance
            state.base_pct = snap.base_pct

        snapshots = self._portfolio.snapshots
        summary = {
            "run_id": run_id,
            "strategy_name": self._strategy.strategy_name,
            "data_source": self._data.source_label,
            "bar_count": len(snapshots),
            "fill_count": self._portfolio.fill_count,
            "total_fees_quote": str(self._portfolio.total_fees_quote),
        }

        if output_dir is not None:
            run_dir = output_dir / run_id
            write_summary(
                run_dir=run_dir,
                run_id=run_id,
                strategy_name=self._strategy.strategy_name,
                config_hash=self._config_hash,
                data_source=self._data.source_label,
                venue=self._venue,
                trading_pair=self._pair,
                start_ts=start_ts,
                end_ts=end_ts,
                snapshots=snapshots,
                fill_count=self._portfolio.fill_count,
                total_fees_quote=self._portfolio.total_fees_quote,
            )
            write_bars(run_dir, snapshots)
            summary["output_dir"] = str(run_dir)

        return summary
