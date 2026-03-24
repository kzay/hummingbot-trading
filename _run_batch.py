"""Run a batch of backtests sequentially and print summary."""
import sys, os, json, time, logging

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))

from controllers.backtesting.config_loader import load_backtest_config
from controllers.backtesting.harness import BacktestHarness

configs = [
    "bot7_mm_12bps",
    "bot7_mm_8bps_3x",
    "bot7_mm_8bps_5x",
    "bot7_mm_15bps_2x",
    "bot7_mm_8bps_invcap",
]

results = {}
for name in configs:
    cfg_path = f"hbot/data/backtest_configs/{name}.yml"
    print(f"\n>>> Running {name} ...", flush=True)
    t0 = time.time()
    try:
        cfg = load_backtest_config(cfg_path)
        harness = BacktestHarness(cfg)
        result = harness.run()
        elapsed = time.time() - t0
        r = {
            "total_return_pct": result.total_return_pct,
            "realized_net_pnl": str(result.realized_net_pnl_quote),
            "residual_pnl": str(result.residual_pnl_quote),
            "closed_trade_count": result.closed_trade_count,
            "fill_count": result.fill_count,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "expectancy": str(result.expectancy_quote),
            "avg_win": str(result.avg_win_quote),
            "avg_loss": str(result.avg_loss_quote),
            "max_drawdown_pct": result.max_drawdown_pct,
            "maker_fill_ratio": result.maker_fill_ratio,
            "total_fees": str(result.total_fees),
        }
        results[name] = r
        print(f"    Done in {elapsed:.0f}s - return: {r['total_return_pct']}%")
    except Exception as e:
        import traceback
        elapsed = time.time() - t0
        print(f"    FAILED in {elapsed:.0f}s - {e}")
        traceback.print_exc()
        results[name] = {"error": str(e)}

print("\n" + "=" * 80)
print("BATCH SUMMARY")
print("=" * 80)
header = f"{'Config':<22} {'Return':>8} {'Fills':>6} {'Trades':>7} {'Win%':>6} {'PF':>6} {'PnL':>10} {'Expect':>8} {'MaxDD':>6} {'Maker%':>7}"
print(header)
print("-" * len(header))
for name, r in results.items():
    if "error" in r:
        print(f"  {name}: ERROR - {r['error']}")
        continue
    pnl = float(r["realized_net_pnl"])
    exp = float(r["expectancy"])
    print(f"{name:<22} {r['total_return_pct']:>7.2f}% {r['fill_count']:>6} {r['closed_trade_count']:>7} {r['win_rate']:>5.1f}% {r['profit_factor']:>6.2f} {pnl:>10.2f} {exp:>8.4f} {r['max_drawdown_pct']:>5.2f}% {r['maker_fill_ratio']:>6.1f}%")
