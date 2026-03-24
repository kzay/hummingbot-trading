"""Test ATR MM best config with leverage on full Q1."""
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

# Test best config (atr0.2_sz0.03) with different leverage levels on Q1
print("=== ATR0.2_SZ0.03 with leverage on Q1 ===\n", flush=True)
header = f"{'Leverage':>8} {'Return':>8} {'PnL':>8} {'Trades':>7} {'WR':>6} {'PF':>6} {'MaxDD':>6} {'Fees':>8}"
print(header, flush=True)
print("-" * len(header), flush=True)

for lev in [1, 2, 3, 5]:
    cfg = make_config(0.2, 0.03, "2025-01-01", "2025-03-31", leverage=lev)
    t0 = time.time()
    harness = BacktestHarness(cfg)
    result = harness.run()
    elapsed = time.time() - t0
    print(f"{lev:>8}x {result.total_return_pct:>+7.2f}% {float(result.realized_net_pnl_quote):>+7.2f} {result.closed_trade_count:>7} {result.win_rate:>5.0%} {result.profit_factor:>6.2f} {result.max_drawdown_pct:>5.2f}% {float(result.total_fees):>8.3f} ({elapsed:.0f}s)", flush=True)

# Also test atr0.3_sz0.02 with leverage
print("\n=== ATR0.3_SZ0.02 with leverage on Q1 ===\n", flush=True)
print(header, flush=True)
print("-" * len(header), flush=True)

for lev in [1, 2, 3, 5]:
    cfg = make_config(0.3, 0.02, "2025-01-01", "2025-03-31", leverage=lev)
    t0 = time.time()
    harness = BacktestHarness(cfg)
    result = harness.run()
    elapsed = time.time() - t0
    print(f"{lev:>8}x {result.total_return_pct:>+7.2f}% {float(result.realized_net_pnl_quote):>+7.2f} {result.closed_trade_count:>7} {result.win_rate:>5.0%} {result.profit_factor:>6.2f} {result.max_drawdown_pct:>5.2f}% {float(result.total_fees):>8.3f} ({elapsed:.0f}s)", flush=True)

# Also test with larger size but same ATR
print("\n=== ATR0.2 with larger sizes on Q1 ===\n", flush=True)
header2 = f"{'Size':>8} {'Return':>8} {'PnL':>8} {'Trades':>7} {'WR':>6} {'PF':>6} {'MaxDD':>6} {'Fees':>8}"
print(header2, flush=True)
print("-" * len(header2), flush=True)

for size_pct in [0.03, 0.04, 0.05, 0.06, 0.08, 0.10]:
    cfg = make_config(0.2, size_pct, "2025-01-01", "2025-03-31")
    t0 = time.time()
    harness = BacktestHarness(cfg)
    result = harness.run()
    elapsed = time.time() - t0
    print(f"{size_pct:>7.2f}% {result.total_return_pct:>+7.2f}% {float(result.realized_net_pnl_quote):>+7.2f} {result.closed_trade_count:>7} {result.win_rate:>5.0%} {result.profit_factor:>6.2f} {result.max_drawdown_pct:>5.2f}% {float(result.total_fees):>8.3f} ({elapsed:.0f}s)", flush=True)

print("\nDone!", flush=True)
