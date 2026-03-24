"""Fine-grained sweep around the proven sweet spot."""
import sys, os, logging, time
from decimal import Decimal

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))

from controllers.backtesting.types import BacktestConfig, DataSourceConfig, SynthesisConfig
from controllers.backtesting.harness import BacktestHarness

def make_config(atr_mult, size_pct, start="2025-01-01", end="2025-03-31"):
    return BacktestConfig(
        strategy_class="",
        strategy_config={
            "adapter_mode": "atr_mm",
            "atr_period": 14,
            "min_warmup_bars": 30,
            "spread_atr_mult": str(atr_mult),
            "base_size_pct": str(size_pct),
            "levels": 3,
            "max_inventory_pct": "0.15",
            "inventory_skew_mult": "3.0",
        },
        data_source=DataSourceConfig(
            exchange="bitget", pair="BTC-USDT", resolution="1m",
            instrument_type="perp", start_date=start, end_date=end,
            catalog_dir="hbot/data/historical",
        ),
        initial_equity=Decimal("500"),
        fill_model="latency_aware",
        seed=42, leverage=1, step_interval_s=60, warmup_bars=60,
        synthesis=SynthesisConfig(
            base_spread_bps=Decimal("8.0"), vol_spread_mult=Decimal("1.5"),
            depth_levels=10, depth_decay=Decimal("0.70"),
            base_depth_size=Decimal("0.5"), steps_per_bar=4,
        ),
        output_dir="hbot/reports/backtest",
    )

atr_values = [0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30, 0.35]
size_values = [0.020, 0.025, 0.028, 0.030, 0.033, 0.035]

results = []
total = len(atr_values) * len(size_values)
print(f"=== FINE SWEEP: {total} combos on Q1 2025 ===\n", flush=True)

idx = 0
for atr in atr_values:
    for sz in size_values:
        idx += 1
        label = f"atr{atr:.2f}_sz{sz:.3f}"
        cfg = make_config(atr, sz)
        t0 = time.time()
        harness = BacktestHarness(cfg)
        result = harness.run()
        elapsed = time.time() - t0
        r = {
            "label": label, "atr": atr, "size": sz,
            "return_pct": result.total_return_pct,
            "pnl": float(result.realized_net_pnl_quote),
            "residual": float(result.residual_pnl_quote),
            "trades": result.closed_trade_count,
            "win_rate": result.win_rate,
            "pf": result.profit_factor,
            "expectancy": float(result.expectancy_quote),
            "avg_win": float(result.avg_win_quote),
            "avg_loss": float(result.avg_loss_quote),
            "max_dd": result.max_drawdown_pct,
        }
        results.append(r)
        s = "+" if r["pnl"] > 0 else "-"
        print(f"[{idx}/{total}] {s} {label}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} pf={r['pf']:.2f} dd={r['max_dd']:.2f}% ({elapsed:.0f}s)", flush=True)

results.sort(key=lambda x: x["pnl"], reverse=True)
print("\n" + "=" * 110, flush=True)
print("TOP 10 BY PnL", flush=True)
print("=" * 110, flush=True)
header = f"{'Label':<20} {'Return':>8} {'PnL':>8} {'Trades':>7} {'WR':>6} {'PF':>6} {'Expect':>8} {'AvgW':>8} {'AvgL':>8} {'MaxDD':>6}"
print(header, flush=True)
print("-" * len(header), flush=True)
for r in results[:10]:
    print(f"{r['label']:<20} {r['return_pct']:>+7.2f}% {r['pnl']:>+8.2f} {r['trades']:>7} {r['win_rate']:>5.0%} {r['pf']:>6.2f} {r['expectancy']:>+8.4f} {r['avg_win']:>8.4f} {r['avg_loss']:>8.4f} {r['max_dd']:>5.2f}%", flush=True)

# Heat map style output
print("\n=== PnL HEAT MAP (ATR x Size) ===\n", flush=True)
atr_label = "ATR\\Size"
print(f"{atr_label:>8}", end="", flush=True)
for sz in size_values:
    print(f"  {sz:>7.3f}", end="", flush=True)
print(flush=True)
print("-" * (8 + 9 * len(size_values)), flush=True)
for atr in atr_values:
    print(f"{atr:>8.2f}", end="", flush=True)
    for sz in size_values:
        match = [r for r in results if r["atr"] == atr and r["size"] == sz]
        if match:
            pnl = match[0]["pnl"]
            print(f"  {pnl:>+7.2f}", end="", flush=True)
        else:
            print(f"  {'N/A':>7}", end="", flush=True)
    print(flush=True)

# Monthly breakdown for #1
if results:
    r = results[0]
    print(f"\n=== MONTHLY BREAKDOWN: {r['label']} ===\n", flush=True)
    for pname, start, end in [("Jan", "2025-01-01", "2025-01-31"), ("Feb", "2025-02-01", "2025-02-28"), ("Mar", "2025-03-01", "2025-03-31")]:
        cfg = make_config(r["atr"], r["size"], start, end)
        harness = BacktestHarness(cfg)
        mr = harness.run()
        print(f"  {pname}: ret={mr.total_return_pct:+.2f}% pnl=${float(mr.realized_net_pnl_quote):+.2f} wr={mr.win_rate:.0%} trades={mr.closed_trade_count} dd={mr.max_drawdown_pct:.2f}%", flush=True)

print("\nDone!", flush=True)
