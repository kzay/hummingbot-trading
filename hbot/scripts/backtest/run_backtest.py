"""CLI entry point for the generic backtest harness.

Usage::

    python scripts/backtest/run_backtest.py \\
        --strategy epp_v2_4 \\
        --event-file reports/event_store/events_20260222.jsonl \\
        --pair BTC-USDT \\
        --initial-base 0.01 \\
        --initial-quote 1000
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_HBOT_ROOT = _SCRIPT_DIR.parents[1]
sys.path.insert(0, str(_HBOT_ROOT))

from scripts.backtest.adapters.epp_v24_adapter import EppV24Adapter
from scripts.backtest.harness.data_provider import EventStoreProvider
from scripts.backtest.harness.fill_simulator import FillSimulator
from scripts.backtest.harness.portfolio_tracker import PortfolioTracker
from scripts.backtest.harness.runner import BacktestRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Generic backtest harness")
    parser.add_argument("--strategy", default="epp_v2_4", choices=["epp_v2_4"])
    parser.add_argument("--event-file", required=True, help="Path to event store JSONL file")
    parser.add_argument("--pair", default="BTC-USDT", help="Trading pair filter")
    parser.add_argument("--venue", default="backtest", help="Venue label")
    parser.add_argument("--initial-base", type=str, default="0.01", help="Initial base balance")
    parser.add_argument("--initial-quote", type=str, default="1000", help="Initial quote balance")
    parser.add_argument("--maker-fee", type=str, default="0.001", help="Maker fee rate")
    parser.add_argument("--taker-fee", type=str, default="0.001", help="Taker fee rate")
    parser.add_argument("--output-dir", default=str(_HBOT_ROOT / "reports" / "backtest" / "runs"))
    args = parser.parse_args()

    if args.strategy == "epp_v2_4":
        strategy = EppV24Adapter()
    else:
        print(f"Unknown strategy: {args.strategy}")
        sys.exit(1)

    data_provider = EventStoreProvider(
        event_file=Path(args.event_file),
        trading_pair=args.pair,
    )

    fill_sim = FillSimulator(
        maker_fee_pct=Decimal(args.maker_fee),
        taker_fee_pct=Decimal(args.taker_fee),
    )

    portfolio = PortfolioTracker(
        initial_base=Decimal(args.initial_base),
        initial_quote=Decimal(args.initial_quote),
    )

    runner = BacktestRunner(
        data_provider=data_provider,
        strategy=strategy,
        fill_sim=fill_sim,
        portfolio=portfolio,
        venue=args.venue,
        trading_pair=args.pair,
    )

    result = runner.run(output_dir=Path(args.output_dir))
    print(f"[backtest] strategy={result.get('strategy_name')}")
    print(f"[backtest] bars={result.get('bar_count')} fills={result.get('fill_count')}")
    print(f"[backtest] fees={result.get('total_fees_quote')}")
    if result.get("output_dir"):
        print(f"[backtest] output={result.get('output_dir')}")


if __name__ == "__main__":
    main()
