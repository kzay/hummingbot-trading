"""Validate top ATR MM configs on individual months."""
import sys, os, logging, time
from decimal import Decimal

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))

from controllers.backtesting.types import BacktestConfig, DataSourceConfig, SynthesisConfig
from controllers.backtesting.harness import BacktestHarness

def make_config(spread_atr_mult, base_size_pct, start, end, leverage=1):
    sc = {
        "adapter_mode": "atr_mm",
        "atr_period": 14,
        "min_warmup_bars": 30,
        "spread_atr_mult": str(spread_atr_mult),
        "base_size_pct": str(base_size_pct),
        "levels": 3,
        "max_inventory_pct": "0.15",
        "inventory_skew_mult": "3.0",
    }
    return BacktestConfig(
        strategy_class="",
        strategy_config=sc,
        data_source=DataSourceConfig(
            exchange="bitget", pair="BTC-USDT", resolution="1m",
            instrument_type="perp", start_date=start, end_date=end,
            catalog_dir="hbot/data/historical",
        ),
        initial_equity=Decimal("500"),
        fill_model="latency_aware",
        seed=42,
        leverage=leverage,
        step_interval_s=60,
        warmup_bars=60,
        synthesis=SynthesisConfig(
            base_spread_bps=Decimal("8.0"),
            vol_spread_mult=Decimal("1.5"),
            depth_levels=10,
            depth_decay=Decimal("0.70"),
            base_depth_size=Decimal("0.5"),
            steps_per_bar=4,
        ),
        output_dir="hbot/reports/backtest",
    )

configs_to_test = [
    ("atr0.2_sz0.03", 0.2, 0.03),
    ("atr0.3_sz0.02", 0.3, 0.02),
    ("atr0.4_sz0.02", 0.4, 0.02),
    ("atr0.5_sz0.02", 0.5, 0.02),
]

periods = [
    ("Jan", "2025-01-01", "2025-01-31"),
    ("Feb", "2025-02-01", "2025-02-28"),
    ("Mar", "2025-03-01", "2025-03-31"),
]

print(f"{'Config':<20}", end="", flush=True)
for pname, _, _ in periods:
    print(f"  {'Return':>8} {'PnL':>7} {'WR':>4} {'Trades':>6} {'MaxDD':>6}", end="", flush=True)
print(flush=True)
print("-" * 120, flush=True)

for cname, atr_mult, size_pct in configs_to_test:
    print(f"{cname:<20}", end="", flush=True)
    for pname, start, end in periods:
        cfg = make_config(atr_mult, size_pct, start, end)
        try:
            harness = BacktestHarness(cfg)
            result = harness.run()
            pnl = float(result.realized_net_pnl_quote)
            print(f"  {result.total_return_pct:>+7.2f}% {pnl:>+6.2f} {result.win_rate:>3.0%} {result.closed_trade_count:>6} {result.max_drawdown_pct:>5.2f}%", end="", flush=True)
        except Exception as e:
            print(f"  {'ERR':>8} {'ERR':>7} {'':>4} {'ERR':>6} {'ERR':>6}", end="", flush=True)
    print(flush=True)

print("\nDone!", flush=True)
