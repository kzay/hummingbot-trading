"""Fast parameter sweep for simple_adapter MM strategy.

Sweeps spread_mult and size_mult — the actual strategy control parameters.
Uses Jan 2025 (1 month) for fast iteration, then validates winners on full Q1.
"""
import sys, os, logging, time
from decimal import Decimal

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))

from controllers.backtesting.types import BacktestConfig, DataSourceConfig, SynthesisConfig
from controllers.backtesting.harness import BacktestHarness

def make_config(spread_mult, size_mult=1.0, start="2025-01-01", end="2025-01-31", leverage=1):
    sc = {
        "adapter_mode": "simple",
        "high_vol_band_pct": "0.010",
        "shock_drift_pct": "0.006",
        "ema_period": 20,
        "atr_period": 14,
        "min_warmup_bars": 30,
        "spread_mult": str(spread_mult),
        "size_mult": str(size_mult),
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

spread_mults = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0]
size_mults = [0.5, 1.0, 2.0, 3.0]

results = []
total = len(spread_mults) * len(size_mults)
print(f"=== PHASE 1: {total} combos on Jan 2025 ===\n", flush=True)

idx = 0
for spread_mult in spread_mults:
    for size_mult in size_mults:
        idx += 1
        label = f"sp{spread_mult}_sz{size_mult}"
        cfg = make_config(spread_mult, size_mult)
        t0 = time.time()
        try:
            harness = BacktestHarness(cfg)
            result = harness.run()
            elapsed = time.time() - t0
            r = {
                "label": label,
                "spread_mult": spread_mult,
                "size_mult": size_mult,
                "return_pct": result.total_return_pct,
                "fills": result.fill_count,
                "trades": result.closed_trade_count,
                "win_rate": result.win_rate,
                "pf": result.profit_factor,
                "pnl": float(result.realized_net_pnl_quote),
                "residual": float(result.residual_pnl_quote),
                "expectancy": float(result.expectancy_quote),
                "avg_win": float(result.avg_win_quote),
                "avg_loss": float(result.avg_loss_quote),
                "max_dd": result.max_drawdown_pct,
                "fees": float(result.total_fees),
                "elapsed": elapsed,
            }
            results.append(r)
            status = "+" if r["pnl"] > 0 else "-"
            print(f"[{idx}/{total}] {status} {label}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} pf={r['pf']:.2f} trades={r['trades']} dd={r['max_dd']:.2f}% ({elapsed:.0f}s)", flush=True)
        except Exception as e:
            print(f"[{idx}/{total}] X {label}: FAILED - {e}", flush=True)

print("\n" + "=" * 120, flush=True)
print("TOP 15 BY REALIZED PnL", flush=True)
print("=" * 120, flush=True)
results.sort(key=lambda x: x["pnl"], reverse=True)
header = f"{'Label':<18} {'Return':>8} {'PnL':>8} {'Resid':>8} {'Trades':>7} {'WinRate':>8} {'PF':>6} {'Expect':>8} {'AvgW':>8} {'AvgL':>8} {'MaxDD':>6} {'Fees':>6}"
print(header, flush=True)
print("-" * len(header), flush=True)
for r in results[:15]:
    print(f"{r['label']:<18} {r['return_pct']:>+7.2f}% {r['pnl']:>+8.2f} {r['residual']:>+8.2f} {r['trades']:>7} {r['win_rate']:>7.0%} {r['pf']:>6.2f} {r['expectancy']:>+8.4f} {r['avg_win']:>8.4f} {r['avg_loss']:>8.4f} {r['max_dd']:>5.2f}% {r['fees']:>6.3f}", flush=True)

# Phase 2: Validate top 5 profitable ones on full Q1
profitable = [r for r in results if r["pnl"] > 0][:5]
if profitable:
    print(f"\n=== PHASE 2: Validating {len(profitable)} profitable configs on Q1 2025 ===\n", flush=True)
    for r in profitable:
        cfg = make_config(r["spread_mult"], r["size_mult"], start="2025-01-01", end="2025-03-31")
        label = f"{r['label']}_Q1"
        t0 = time.time()
        try:
            harness = BacktestHarness(cfg)
            result = harness.run()
            elapsed = time.time() - t0
            print(f"  {label}: ret={result.total_return_pct:+.2f}% pnl=${float(result.realized_net_pnl_quote):+.2f} wr={result.win_rate:.0%} pf={result.profit_factor:.2f} trades={result.closed_trade_count} dd={result.max_drawdown_pct:.2f}% ({elapsed:.0f}s)", flush=True)
        except Exception as e:
            print(f"  {label}: FAILED - {e}", flush=True)
else:
    print("\nNo profitable configs found in Phase 1. Best was:", flush=True)
    if results:
        r = results[0]
        print(f"  {r['label']}: pnl=${r['pnl']:+.2f}", flush=True)
    
    print("\n=== PHASE 2: Validating top 3 on Q1 anyway ===\n", flush=True)
    for r in results[:3]:
        cfg = make_config(r["spread_mult"], r["size_mult"], start="2025-01-01", end="2025-03-31")
        label = f"{r['label']}_Q1"
        t0 = time.time()
        try:
            harness = BacktestHarness(cfg)
            result = harness.run()
            elapsed = time.time() - t0
            print(f"  {label}: ret={result.total_return_pct:+.2f}% pnl=${float(result.realized_net_pnl_quote):+.2f} wr={result.win_rate:.0%} pf={result.profit_factor:.2f} trades={result.closed_trade_count} dd={result.max_drawdown_pct:.2f}% ({elapsed:.0f}s)", flush=True)
        except Exception as e:
            print(f"  {label}: FAILED - {e}", flush=True)
