"""Stress test the best v1 config under different fill model assumptions."""
import sys, os, logging, time
from decimal import Decimal

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))

from controllers.backtesting.types import BacktestConfig, DataSourceConfig, SynthesisConfig
from controllers.backtesting.harness import BacktestHarness

def make_config(fill_preset, start="2025-01-01", end="2025-03-31"):
    sc = {
        "adapter_mode": "atr_mm",
        "atr_period": 14,
        "min_warmup_bars": 30,
        "spread_atr_mult": "0.2",
        "base_size_pct": "0.03",
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
        fill_model_preset=fill_preset,
        seed=42,
        leverage=1,
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

print("=== FILL MODEL STRESS TEST: v1 atr0.2_sz0.03 on Q1 ===\n", flush=True)
header = f"{'Preset':<15} {'Return':>8} {'PnL':>8} {'Trades':>7} {'WR':>6} {'PF':>6} {'Expect':>8} {'AvgW':>8} {'AvgL':>8} {'MaxDD':>6} {'Fees':>8} {'Maker%':>7}"
print(header, flush=True)
print("-" * len(header), flush=True)

for preset in ["optimistic", "balanced", "conservative", "pessimistic"]:
    cfg = make_config(preset)
    t0 = time.time()
    harness = BacktestHarness(cfg)
    result = harness.run()
    elapsed = time.time() - t0
    print(f"{preset:<15} {result.total_return_pct:>+7.2f}% {float(result.realized_net_pnl_quote):>+7.2f} {result.closed_trade_count:>7} {result.win_rate:>5.0%} {result.profit_factor:>6.2f} {float(result.expectancy_quote):>+8.4f} {float(result.avg_win_quote):>8.4f} {float(result.avg_loss_quote):>8.4f} {result.max_drawdown_pct:>5.2f}% {float(result.total_fees):>8.3f} {result.maker_fill_ratio:>6.0%} ({elapsed:.0f}s)", flush=True)

# Also test with different seeds (stochastic stability check)
print("\n=== SEED STABILITY TEST: v1 atr0.2_sz0.03 balanced ===\n", flush=True)
header2 = f"{'Seed':>6} {'Return':>8} {'PnL':>8} {'Trades':>7} {'WR':>6} {'PF':>6} {'MaxDD':>6}"
print(header2, flush=True)
print("-" * len(header2), flush=True)

for seed in [42, 7, 123, 999, 12345, 54321]:
    cfg = make_config("balanced")
    cfg.seed = seed
    t0 = time.time()
    harness = BacktestHarness(cfg)
    result = harness.run()
    elapsed = time.time() - t0
    print(f"{seed:>6} {result.total_return_pct:>+7.2f}% {float(result.realized_net_pnl_quote):>+7.2f} {result.closed_trade_count:>7} {result.win_rate:>5.0%} {result.profit_factor:>6.2f} {result.max_drawdown_pct:>5.2f}% ({elapsed:.0f}s)", flush=True)

print("\nDone!", flush=True)
