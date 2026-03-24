"""Sweep ATR MM v2 configurations on Q1 2025, testing HTF + vol-sizing impact."""
import sys, os, logging, time
from decimal import Decimal

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))

from controllers.backtesting.types import BacktestConfig, DataSourceConfig, SynthesisConfig
from controllers.backtesting.harness import BacktestHarness

def make_config(adapter_mode, spread_atr_mult, base_size_pct,
                htf_enabled=True, vol_sizing=True,
                htf_bars=15, htf_contra=0.3,
                start="2025-01-01", end="2025-03-31"):
    sc = {
        "adapter_mode": adapter_mode,
        "atr_period": 14,
        "min_warmup_bars": 30,
        "spread_atr_mult": str(spread_atr_mult),
        "base_size_pct": str(base_size_pct),
        "levels": 3,
        "max_inventory_pct": "0.15",
        "inventory_skew_mult": "3.0",
        "htf_enabled": htf_enabled,
        "vol_sizing_enabled": vol_sizing,
        "htf_bars": htf_bars,
        "htf_contra_size_mult": str(htf_contra),
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

def run_one(label, cfg):
    t0 = time.time()
    try:
        harness = BacktestHarness(cfg)
        result = harness.run()
        elapsed = time.time() - t0
        return {
            "label": label,
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
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"label": label, "error": str(e)}

results = []

# --- Group 1: v1 baseline (best configs from previous sweep) ---
print("=== GROUP 1: ATR MM v1 Baselines ===\n", flush=True)
for atr, sz in [(0.2, 0.03), (0.3, 0.02)]:
    label = f"v1_atr{atr}_sz{sz}"
    cfg = make_config("atr_mm", atr, sz)
    r = run_one(label, cfg)
    results.append(r)
    if "error" not in r:
        print(f"  {label}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} dd={r['max_dd']:.2f}%", flush=True)
    else:
        print(f"  {label}: FAILED - {r['error']}", flush=True)

# --- Group 2: v2 with all features ---
print("\n=== GROUP 2: ATR MM v2 (HTF+VolSizing) ===\n", flush=True)
for atr, sz in [(0.2, 0.025), (0.2, 0.03), (0.3, 0.02), (0.3, 0.025), (0.25, 0.025)]:
    label = f"v2_full_atr{atr}_sz{sz}"
    cfg = make_config("atr_mm_v2", atr, sz, htf_enabled=True, vol_sizing=True)
    r = run_one(label, cfg)
    results.append(r)
    if "error" not in r:
        print(f"  {label}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} dd={r['max_dd']:.2f}%", flush=True)
    else:
        print(f"  {label}: FAILED - {r['error']}", flush=True)

# --- Group 3: v2 with only HTF (no vol sizing) ---
print("\n=== GROUP 3: v2 HTF Only ===\n", flush=True)
for atr, sz in [(0.2, 0.03), (0.3, 0.02)]:
    label = f"v2_htf_atr{atr}_sz{sz}"
    cfg = make_config("atr_mm_v2", atr, sz, htf_enabled=True, vol_sizing=False)
    r = run_one(label, cfg)
    results.append(r)
    if "error" not in r:
        print(f"  {label}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} dd={r['max_dd']:.2f}%", flush=True)
    else:
        print(f"  {label}: FAILED - {r['error']}", flush=True)

# --- Group 4: v2 with only vol sizing (no HTF) ---
print("\n=== GROUP 4: v2 VolSizing Only ===\n", flush=True)
for atr, sz in [(0.2, 0.03), (0.3, 0.02)]:
    label = f"v2_vol_atr{atr}_sz{sz}"
    cfg = make_config("atr_mm_v2", atr, sz, htf_enabled=False, vol_sizing=True)
    r = run_one(label, cfg)
    results.append(r)
    if "error" not in r:
        print(f"  {label}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} dd={r['max_dd']:.2f}%", flush=True)
    else:
        print(f"  {label}: FAILED - {r['error']}", flush=True)

# --- Group 5: v2 with different HTF periods ---
print("\n=== GROUP 5: v2 HTF Period Variations ===\n", flush=True)
for htf_bars in [5, 15, 30, 60]:
    label = f"v2_htf{htf_bars}m_atr0.25"
    cfg = make_config("atr_mm_v2", 0.25, 0.025, htf_bars=htf_bars)
    r = run_one(label, cfg)
    results.append(r)
    if "error" not in r:
        print(f"  {label}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} dd={r['max_dd']:.2f}%", flush=True)
    else:
        print(f"  {label}: FAILED - {r['error']}", flush=True)

# --- Summary ---
valid = [r for r in results if "error" not in r]
valid.sort(key=lambda x: x["pnl"], reverse=True)
print("\n" + "=" * 130, flush=True)
print("ALL RESULTS RANKED BY PnL", flush=True)
print("=" * 130, flush=True)
header = f"{'Label':<30} {'Return':>8} {'PnL':>8} {'Resid':>8} {'Trades':>7} {'WR':>6} {'PF':>6} {'Expect':>8} {'AvgW':>8} {'AvgL':>8} {'MaxDD':>6}"
print(header, flush=True)
print("-" * len(header), flush=True)
for r in valid:
    print(f"{r['label']:<30} {r['return_pct']:>+7.2f}% {r['pnl']:>+8.2f} {r['residual']:>+8.2f} {r['trades']:>7} {r['win_rate']:>5.0%} {r['pf']:>6.2f} {r['expectancy']:>+8.4f} {r['avg_win']:>8.4f} {r['avg_loss']:>8.4f} {r['max_dd']:>5.2f}%", flush=True)

# For top 3, run monthly breakdown
print("\n" + "=" * 130, flush=True)
print("MONTHLY BREAKDOWN FOR TOP 3", flush=True)
print("=" * 130, flush=True)
top3 = valid[:3]
for r in top3:
    atr_mult = float(r["label"].split("atr")[1].split("_")[0])
    sz = float(r["label"].split("sz")[1]) if "sz" in r["label"] else 0.025
    mode = "atr_mm_v2" if "v2" in r["label"] else "atr_mm"
    htf = "htf" in r["label"] or "full" in r["label"]
    vol = "vol" in r["label"] or "full" in r["label"]
    htf_bars_val = 15
    if "htf" in r["label"] and "m_" in r["label"]:
        htf_bars_val = int(r["label"].split("htf")[1].split("m")[0])

    print(f"\n  {r['label']}:", flush=True)
    for pname, start, end in [("Jan", "2025-01-01", "2025-01-31"), ("Feb", "2025-02-01", "2025-02-28"), ("Mar", "2025-03-01", "2025-03-31")]:
        cfg = make_config(mode, atr_mult, sz, htf_enabled=htf, vol_sizing=vol, htf_bars=htf_bars_val, start=start, end=end)
        mr = run_one(f"{r['label']}_{pname}", cfg)
        if "error" not in mr:
            print(f"    {pname}: ret={mr['return_pct']:+.2f}% pnl=${mr['pnl']:+.2f} wr={mr['win_rate']:.0%} trades={mr['trades']} dd={mr['max_dd']:.2f}%", flush=True)

print("\nDone!", flush=True)
