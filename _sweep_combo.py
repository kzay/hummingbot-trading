"""Comprehensive combo MM sweep — test all feature combinations."""
import sys, os, logging, time, itertools
from decimal import Decimal

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))

from controllers.backtesting.types import BacktestConfig, DataSourceConfig, SynthesisConfig
from controllers.backtesting.harness import BacktestHarness

def make_config(features, atr=0.22, sz=0.030, start="2025-01-01", end="2025-03-31", seed=42, **overrides):
    sc = {
        "adapter_mode": "combo_mm",
        "atr_period": 14,
        "min_warmup_bars": 30,
        "spread_atr_mult": str(atr),
        "base_size_pct": str(sz),
        "levels": 3,
        "max_inventory_pct": "0.15",
        "inventory_skew_mult": "3.0",
        "inventory_age_decay_minutes": 45,
        "urgency_spread_reduction": "0.4",
        "fvg_enabled": "fvg" in features,
        "micro_enabled": "micro" in features,
        "fill_feedback_enabled": "fill_fb" in features,
        "adaptive_inventory_enabled": "adapt_inv" in features,
        "level_sizing_enabled": "level_sz" in features,
        "momentum_guard_enabled": "mom_guard" in features,
    }
    sc.update(overrides)
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
        seed=seed, leverage=1, step_interval_s=60, warmup_bars=60,
        synthesis=SynthesisConfig(
            base_spread_bps=Decimal("8.0"), vol_spread_mult=Decimal("1.5"),
            depth_levels=10, depth_decay=Decimal("0.70"),
            base_depth_size=Decimal("0.5"), steps_per_bar=4,
        ),
        output_dir="hbot/reports/backtest",
    )

def make_v1(atr=0.22, sz=0.030, start="2025-01-01", end="2025-03-31", seed=42):
    return BacktestConfig(
        strategy_class="",
        strategy_config={
            "adapter_mode": "atr_mm",
            "atr_period": 14, "min_warmup_bars": 30,
            "spread_atr_mult": str(atr), "base_size_pct": str(sz),
            "levels": 3, "max_inventory_pct": "0.15", "inventory_skew_mult": "3.0",
        },
        data_source=DataSourceConfig(
            exchange="bitget", pair="BTC-USDT", resolution="1m",
            instrument_type="perp", start_date=start, end_date=end,
            catalog_dir="hbot/data/historical",
        ),
        initial_equity=Decimal("500"),
        fill_model="latency_aware",
        seed=seed, leverage=1, step_interval_s=60, warmup_bars=60,
        synthesis=SynthesisConfig(
            base_spread_bps=Decimal("8.0"), vol_spread_mult=Decimal("1.5"),
            depth_levels=10, depth_decay=Decimal("0.70"),
            base_depth_size=Decimal("0.5"), steps_per_bar=4,
        ),
        output_dir="hbot/reports/backtest",
    )

def run(label, cfg):
    t0 = time.time()
    try:
        h = BacktestHarness(cfg)
        r = h.run()
        return {
            "label": label,
            "ret": r.total_return_pct,
            "pnl": float(r.realized_net_pnl_quote),
            "resid": float(r.residual_pnl_quote),
            "tot": float(r.realized_net_pnl_quote) + float(r.residual_pnl_quote),
            "trades": r.closed_trade_count,
            "wr": r.win_rate,
            "pf": r.profit_factor,
            "exp": float(r.expectancy_quote),
            "dd": r.max_drawdown_pct,
            "t": time.time() - t0,
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"label": label, "error": str(e)}

results = []
ALL_FEATURES = ["fvg", "micro", "fill_fb", "adapt_inv", "level_sz", "mom_guard"]

# --- Phase 1: Baseline ---
print("=== PHASE 1: BASELINES ===\n", flush=True)
for atr in [0.20, 0.22]:
    r = run(f"v1_atr{atr}", make_v1(atr=atr))
    results.append(r)
    if "error" not in r:
        print(f"  {r['label']}: ret={r['ret']:+.2f}% pnl=${r['pnl']:+.2f} tot=${r['tot']:+.2f} trades={r['trades']} wr={r['wr']:.0%} pf={r['pf']:.2f} dd={r['dd']:.2f}%", flush=True)

# Combo baseline (no features)
r = run("combo_none", make_config(set()))
results.append(r)
if "error" not in r:
    print(f"  {r['label']}: ret={r['ret']:+.2f}% pnl=${r['pnl']:+.2f} tot=${r['tot']:+.2f} trades={r['trades']} wr={r['wr']:.0%} pf={r['pf']:.2f} dd={r['dd']:.2f}%", flush=True)

# --- Phase 2: Single features ---
print("\n=== PHASE 2: SINGLE FEATURES ===\n", flush=True)
for feat in ALL_FEATURES:
    r = run(f"single_{feat}", make_config({feat}))
    results.append(r)
    if "error" not in r:
        print(f"  {r['label']}: ret={r['ret']:+.2f}% pnl=${r['pnl']:+.2f} tot=${r['tot']:+.2f} trades={r['trades']} wr={r['wr']:.0%} pf={r['pf']:.2f} dd={r['dd']:.2f}%", flush=True)

# --- Phase 3: All pairs ---
print("\n=== PHASE 3: FEATURE PAIRS ===\n", flush=True)
for pair in itertools.combinations(ALL_FEATURES, 2):
    name = "+".join(pair)
    r = run(f"pair_{name}", make_config(set(pair)))
    results.append(r)
    if "error" not in r:
        s = "+" if r["pnl"] > 0 else "-"
        print(f"  {s} pair_{name}: ret={r['ret']:+.2f}% pnl=${r['pnl']:+.2f} trades={r['trades']} pf={r['pf']:.2f}", flush=True)

# --- Phase 4: Best triples ---
print("\n=== PHASE 4: FEATURE TRIPLES ===\n", flush=True)
for triple in itertools.combinations(ALL_FEATURES, 3):
    name = "+".join(triple)
    r = run(f"tri_{name}", make_config(set(triple)))
    results.append(r)
    if "error" not in r:
        s = "+" if r["pnl"] > 0 else "-"
        print(f"  {s} tri_{name}: ret={r['ret']:+.2f}% pnl=${r['pnl']:+.2f} trades={r['trades']} pf={r['pf']:.2f}", flush=True)

# --- Phase 5: Quads and all ---
print("\n=== PHASE 5: QUADS+ ===\n", flush=True)
for quad in itertools.combinations(ALL_FEATURES, 4):
    name = "+".join(quad)
    r = run(f"quad_{name}", make_config(set(quad)))
    results.append(r)
    if "error" not in r:
        s = "+" if r["pnl"] > 0 else "-"
        print(f"  {s} quad_{name}: ret={r['ret']:+.2f}% pnl=${r['pnl']:+.2f} trades={r['trades']} pf={r['pf']:.2f}", flush=True)

for quint in itertools.combinations(ALL_FEATURES, 5):
    name = "+".join(quint)
    r = run(f"quint_{name}", make_config(set(quint)))
    results.append(r)
    if "error" not in r:
        s = "+" if r["pnl"] > 0 else "-"
        print(f"  {s} quint_{name}: ret={r['ret']:+.2f}% pnl=${r['pnl']:+.2f} trades={r['trades']} pf={r['pf']:.2f}", flush=True)

r = run("all_features", make_config(set(ALL_FEATURES)))
results.append(r)
if "error" not in r:
    s = "+" if r["pnl"] > 0 else "-"
    print(f"  {s} all_features: ret={r['ret']:+.2f}% pnl=${r['pnl']:+.2f} trades={r['trades']} pf={r['pf']:.2f}", flush=True)

# --- Summary ---
valid = [r for r in results if "error" not in r]
valid.sort(key=lambda x: x["tot"], reverse=True)

print("\n" + "=" * 130, flush=True)
print("TOP 20 BY TOTAL PnL (realized + residual)", flush=True)
print("=" * 130, flush=True)
header = f"{'Label':<50} {'Return':>8} {'PnL':>8} {'Resid':>8} {'Total':>8} {'Trades':>7} {'WR':>6} {'PF':>6} {'Expect':>8} {'MaxDD':>6}"
print(header, flush=True)
print("-" * len(header), flush=True)
for r in valid[:20]:
    print(f"{r['label']:<50} {r['ret']:>+7.2f}% {r['pnl']:>+8.2f} {r['resid']:>+8.2f} {r['tot']:>+8.2f} {r['trades']:>7} {r['wr']:>5.0%} {r['pf']:>6.2f} {r['exp']:>+8.4f} {r['dd']:>5.2f}%", flush=True)

# Cross-validation for top 5: monthly + seed
print("\n" + "=" * 130, flush=True)
print("CROSS-VALIDATION FOR TOP 5", flush=True)
print("=" * 130, flush=True)

for rank, r in enumerate(valid[:5]):
    label = r["label"]
    print(f"\n  [{rank+1}] {label}:", flush=True)

    # Figure out which features are on
    features = set()
    for feat in ALL_FEATURES:
        if feat in label:
            features.add(feat)
    is_v1 = label.startswith("v1_")

    # Monthly
    for pname, start, end in [("Jan", "2025-01-01", "2025-01-31"), ("Feb", "2025-02-01", "2025-02-28"), ("Mar", "2025-03-01", "2025-03-31")]:
        if is_v1:
            atr_val = float(label.split("atr")[1])
            cfg = make_v1(atr=atr_val, start=start, end=end)
        else:
            cfg = make_config(features, start=start, end=end)
        mr = run(f"{label}_{pname}", cfg)
        if "error" not in mr:
            print(f"    {pname}: ret={mr['ret']:+.2f}% pnl=${mr['pnl']:+.2f} wr={mr['wr']:.0%} trades={mr['trades']} dd={mr['dd']:.2f}%", flush=True)

    # Seed stability (3 seeds)
    seed_results = []
    for seed in [42, 123, 999]:
        if is_v1:
            cfg = make_v1(atr=float(label.split("atr")[1]), seed=seed)
        else:
            cfg = make_config(features, seed=seed)
        sr = run(f"{label}_seed{seed}", cfg)
        if "error" not in sr:
            seed_results.append(sr)
    if seed_results:
        pnls = [s["pnl"] for s in seed_results]
        print(f"    Seeds: {' / '.join(f'${p:+.2f}' for p in pnls)}  all_positive={all(p > 0 for p in pnls)}", flush=True)

    # Conservative fills
    # Need to rebuild with conservative preset — skip for v1 since we already know
    if not is_v1:
        from controllers.backtesting.types import BacktestConfig as BC
        cfg = make_config(features)
        cfg.fill_model_preset = "conservative"
        cr = run(f"{label}_conservative", cfg)
        if "error" not in cr:
            print(f"    Conservative fills: ret={cr['ret']:+.2f}% pnl=${cr['pnl']:+.2f} wr={cr['wr']:.0%} trades={cr['trades']}", flush=True)

print("\nDone!", flush=True)
