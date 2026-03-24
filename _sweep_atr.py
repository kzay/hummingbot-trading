"""Parameter sweep for ATR-adaptive MM strategy."""
import sys, os, logging, time
from decimal import Decimal

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))

from controllers.backtesting.types import BacktestConfig, DataSourceConfig, SynthesisConfig
from controllers.backtesting.harness import BacktestHarness

def make_config(spread_atr_mult, base_size_pct=0.02, levels=3, inv_max=0.15,
                inv_skew=3.0, start="2025-01-01", end="2025-03-31", leverage=1):
    sc = {
        "adapter_mode": "atr_mm",
        "atr_period": 14,
        "min_warmup_bars": 30,
        "spread_atr_mult": str(spread_atr_mult),
        "base_size_pct": str(base_size_pct),
        "levels": levels,
        "max_inventory_pct": str(inv_max),
        "inventory_skew_mult": str(inv_skew),
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

# Sweep spread_atr_mult x base_size_pct on full Q1
atr_mults = [0.2, 0.3, 0.4, 0.5, 0.7, 1.0, 1.5, 2.0]
size_pcts = [0.01, 0.02, 0.03, 0.05]

results = []
total = len(atr_mults) * len(size_pcts)
print(f"=== ATR MM SWEEP: {total} combos on Q1 2025 ===\n", flush=True)

idx = 0
for atr_mult in atr_mults:
    for size_pct in size_pcts:
        idx += 1
        label = f"atr{atr_mult}_sz{size_pct}"
        cfg = make_config(atr_mult, size_pct)
        t0 = time.time()
        try:
            harness = BacktestHarness(cfg)
            result = harness.run()
            elapsed = time.time() - t0
            r = {
                "label": label,
                "atr_mult": atr_mult,
                "size_pct": size_pct,
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
            import traceback
            print(f"[{idx}/{total}] X {label}: FAILED - {e}", flush=True)
            traceback.print_exc()

print("\n" + "=" * 120, flush=True)
print("TOP 15 BY REALIZED PnL", flush=True)
print("=" * 120, flush=True)
results.sort(key=lambda x: x["pnl"], reverse=True)
header = f"{'Label':<20} {'Return':>8} {'PnL':>8} {'Resid':>8} {'Trades':>7} {'WinRate':>8} {'PF':>6} {'Expect':>8} {'AvgW':>8} {'AvgL':>8} {'MaxDD':>6} {'Fees':>6}"
print(header, flush=True)
print("-" * len(header), flush=True)
for r in results[:15]:
    print(f"{r['label']:<20} {r['return_pct']:>+7.2f}% {r['pnl']:>+8.2f} {r['residual']:>+8.2f} {r['trades']:>7} {r['win_rate']:>7.0%} {r['pf']:>6.2f} {r['expectancy']:>+8.4f} {r['avg_win']:>8.4f} {r['avg_loss']:>8.4f} {r['max_dd']:>5.2f}% {r['fees']:>6.3f}", flush=True)

print("\n" + "=" * 120, flush=True)
print("TOP 10 BY RISK-ADJUSTED RETURN (Return/MaxDD)", flush=True)
print("=" * 120, flush=True)
for r in results:
    r["risk_adj"] = r["return_pct"] / max(r["max_dd"], 0.01) if r["trades"] > 0 else -999
results.sort(key=lambda x: x["risk_adj"], reverse=True)
print(header, flush=True)
print("-" * len(header), flush=True)
for r in results[:10]:
    print(f"{r['label']:<20} {r['return_pct']:>+7.2f}% {r['pnl']:>+8.2f} {r['residual']:>+8.2f} {r['trades']:>7} {r['win_rate']:>7.0%} {r['pf']:>6.2f} {r['expectancy']:>+8.4f} {r['avg_win']:>8.4f} {r['avg_loss']:>8.4f} {r['max_dd']:>5.2f}% {r['fees']:>6.3f}", flush=True)
