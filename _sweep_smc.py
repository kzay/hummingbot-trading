"""Sweep SMC MM vs ATR MM v1 baseline, with feature ablation."""
import sys, os, logging, time
from decimal import Decimal

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))

from controllers.backtesting.types import BacktestConfig, DataSourceConfig, SynthesisConfig
from controllers.backtesting.harness import BacktestHarness

def make_config(adapter_mode, spread_atr_mult, base_size_pct,
                fvg_enabled=True, bb_enabled=True,
                fvg_spread_bias=0.3, fvg_decay_bars=10,
                bb_walk_size_mult=0.5, bb_contract_size_mult=1.3,
                start="2025-01-01", end="2025-03-31", seed=42):
    sc = {
        "adapter_mode": adapter_mode,
        "atr_period": 14,
        "min_warmup_bars": 30,
        "spread_atr_mult": str(spread_atr_mult),
        "base_size_pct": str(base_size_pct),
        "levels": 3,
        "max_inventory_pct": "0.15",
        "inventory_skew_mult": "3.0",
        "inventory_age_decay_minutes": 45,
        "urgency_spread_reduction": "0.4",
    }
    if adapter_mode == "smc_mm":
        sc.update({
            "fvg_enabled": fvg_enabled,
            "bb_enabled": bb_enabled,
            "fvg_spread_bias": str(fvg_spread_bias),
            "fvg_decay_bars": fvg_decay_bars,
            "bb_walk_size_mult": str(bb_walk_size_mult),
            "bb_contract_size_mult": str(bb_contract_size_mult),
        })
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
        seed=seed,
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
            "pnl": float(result.realized_net_pnl_quote),
            "residual": float(result.residual_pnl_quote),
            "trades": result.closed_trade_count,
            "win_rate": result.win_rate,
            "pf": result.profit_factor,
            "expectancy": float(result.expectancy_quote),
            "avg_win": float(result.avg_win_quote),
            "avg_loss": float(result.avg_loss_quote),
            "max_dd": result.max_drawdown_pct,
            "elapsed": elapsed,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"label": label, "error": str(e)}

results = []

# Group 1: Baselines (v1 at both the old and new champion configs)
print("=== GROUP 1: ATR MM v1 Baselines ===\n", flush=True)
for atr, sz, name in [(0.20, 0.030, "v1_0.20_champion"), (0.22, 0.030, "v1_0.22_champion")]:
    r = run_one(name, make_config("atr_mm", atr, sz))
    results.append(r)
    if "error" not in r:
        print(f"  {name}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} pf={r['pf']:.2f} dd={r['max_dd']:.2f}%", flush=True)

# Group 2: SMC MM with all features (sweep atr/size around sweet spot)
print("\n=== GROUP 2: SMC MM (FVG+BB) ===\n", flush=True)
for atr, sz in [(0.20, 0.030), (0.22, 0.030), (0.18, 0.030), (0.25, 0.030), (0.22, 0.025)]:
    name = f"smc_full_atr{atr}_sz{sz}"
    r = run_one(name, make_config("smc_mm", atr, sz, fvg_enabled=True, bb_enabled=True))
    results.append(r)
    if "error" not in r:
        print(f"  {name}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} pf={r['pf']:.2f} dd={r['max_dd']:.2f}%", flush=True)

# Group 3: FVG only (no BB)
print("\n=== GROUP 3: SMC (FVG Only) ===\n", flush=True)
for atr, sz in [(0.22, 0.030), (0.20, 0.030)]:
    name = f"smc_fvg_atr{atr}_sz{sz}"
    r = run_one(name, make_config("smc_mm", atr, sz, fvg_enabled=True, bb_enabled=False))
    results.append(r)
    if "error" not in r:
        print(f"  {name}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} pf={r['pf']:.2f} dd={r['max_dd']:.2f}%", flush=True)

# Group 4: BB only (no FVG)
print("\n=== GROUP 4: SMC (BB Only) ===\n", flush=True)
for atr, sz in [(0.22, 0.030), (0.20, 0.030)]:
    name = f"smc_bb_atr{atr}_sz{sz}"
    r = run_one(name, make_config("smc_mm", atr, sz, fvg_enabled=False, bb_enabled=True))
    results.append(r)
    if "error" not in r:
        print(f"  {name}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} pf={r['pf']:.2f} dd={r['max_dd']:.2f}%", flush=True)

# Group 5: FVG parameter variations
print("\n=== GROUP 5: FVG Bias Variations ===\n", flush=True)
for bias in [0.15, 0.3, 0.5, 0.7]:
    for decay in [5, 10, 20]:
        name = f"smc_bias{bias}_decay{decay}"
        r = run_one(name, make_config("smc_mm", 0.22, 0.030, fvg_spread_bias=bias, fvg_decay_bars=decay))
        results.append(r)
        if "error" not in r:
            print(f"  {name}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} pf={r['pf']:.2f} dd={r['max_dd']:.2f}%", flush=True)

# Group 6: BB parameter variations
print("\n=== GROUP 6: BB Sizing Variations ===\n", flush=True)
for walk_mult in [0.3, 0.5, 0.7]:
    for contract_mult in [1.0, 1.3, 1.5]:
        name = f"smc_walk{walk_mult}_contr{contract_mult}"
        r = run_one(name, make_config("smc_mm", 0.22, 0.030, bb_walk_size_mult=walk_mult, bb_contract_size_mult=contract_mult))
        results.append(r)
        if "error" not in r:
            print(f"  {name}: ret={r['return_pct']:+.2f}% pnl=${r['pnl']:+.2f} wr={r['win_rate']:.0%} trades={r['trades']} pf={r['pf']:.2f} dd={r['max_dd']:.2f}%", flush=True)

# Summary
valid = [r for r in results if "error" not in r]
valid.sort(key=lambda x: x["pnl"], reverse=True)
print("\n" + "=" * 120, flush=True)
print("ALL RESULTS RANKED BY PnL", flush=True)
print("=" * 120, flush=True)
header = f"{'Label':<35} {'Return':>8} {'PnL':>8} {'Resid':>8} {'Trades':>7} {'WR':>6} {'PF':>6} {'Expect':>8} {'MaxDD':>6}"
print(header, flush=True)
print("-" * len(header), flush=True)
for r in valid:
    print(f"{r['label']:<35} {r['return_pct']:>+7.2f}% {r['pnl']:>+8.2f} {r['residual']:>+8.2f} {r['trades']:>7} {r['win_rate']:>5.0%} {r['pf']:>6.2f} {r['expectancy']:>+8.4f} {r['max_dd']:>5.2f}%", flush=True)

# Monthly breakdown for top 3
print("\n" + "=" * 120, flush=True)
print("MONTHLY BREAKDOWN FOR TOP 3", flush=True)
print("=" * 120, flush=True)
for r in valid[:3]:
    # Parse params from label
    label = r["label"]
    if "smc" in label:
        mode = "smc_mm"
    else:
        mode = "atr_mm"
    # Use the best params from the label
    print(f"\n  {label}:", flush=True)
    for pname, start, end in [("Jan", "2025-01-01", "2025-01-31"), ("Feb", "2025-02-01", "2025-02-28"), ("Mar", "2025-03-01", "2025-03-31")]:
        if label == "v1_0.22_champion":
            cfg = make_config("atr_mm", 0.22, 0.030, start=start, end=end)
        elif label == "v1_0.20_champion":
            cfg = make_config("atr_mm", 0.20, 0.030, start=start, end=end)
        elif "bias" in label:
            parts = label.split("_")
            bias = float(parts[1].replace("bias", ""))
            decay = int(parts[2].replace("decay", ""))
            cfg = make_config("smc_mm", 0.22, 0.030, fvg_spread_bias=bias, fvg_decay_bars=decay, start=start, end=end)
        elif "walk" in label:
            parts = label.split("_")
            walk = float(parts[1].replace("walk", ""))
            contr = float(parts[2].replace("contr", ""))
            cfg = make_config("smc_mm", 0.22, 0.030, bb_walk_size_mult=walk, bb_contract_size_mult=contr, start=start, end=end)
        else:
            atr_val = float(label.split("atr")[1].split("_")[0])
            sz_val = float(label.split("sz")[1])
            fvg = "fvg" in label or "full" in label
            bb = "bb" in label or "full" in label
            cfg = make_config(mode, atr_val, sz_val, fvg_enabled=fvg, bb_enabled=bb, start=start, end=end)
        mr = run_one(f"{label}_{pname}", cfg)
        if "error" not in mr:
            print(f"    {pname}: ret={mr['return_pct']:+.2f}% pnl=${mr['pnl']:+.2f} wr={mr['win_rate']:.0%} trades={mr['trades']} dd={mr['max_dd']:.2f}%", flush=True)

print("\nDone!", flush=True)
