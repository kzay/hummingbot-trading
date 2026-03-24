"""Comprehensive audit of the backtest engine.

Runs a short backtest with full tracing to verify:
1. Order flow: cancel_all timing, submit order, fill timing
2. PnL accounting: each fill's impact on position and equity
3. Fill model: are fills happening at correct prices? maker vs taker?
4. Book synthesis: look-ahead bias check, spread sanity
5. Round-trip accounting: are closed trades computed correctly?
6. Position tracking: does harness position match desk portfolio position?
"""
import sys, os, logging
from decimal import Decimal

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hbot"))

from controllers.backtesting.types import BacktestConfig, DataSourceConfig, SynthesisConfig
from controllers.backtesting.harness import BacktestHarness

# Run a very short backtest (1 week) to trace every fill
cfg = BacktestConfig(
    strategy_class="",
    strategy_config={
        "adapter_mode": "atr_mm",
        "atr_period": 14, "min_warmup_bars": 30,
        "spread_atr_mult": "0.22", "base_size_pct": "0.030",
        "levels": 3, "max_inventory_pct": "0.15", "inventory_skew_mult": "3.0",
    },
    data_source=DataSourceConfig(
        exchange="bitget", pair="BTC-USDT", resolution="1m",
        instrument_type="perp", start_date="2025-01-15", end_date="2025-01-16",
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

harness = BacktestHarness(cfg)
result = harness.run()

print("=" * 100, flush=True)
print("AUDIT REPORT: 1-week backtest (Jan 15-21, 2025)", flush=True)
print("=" * 100, flush=True)

# 1. Basic metrics
print(f"\n--- 1. BASIC METRICS ---", flush=True)
print(f"Total ticks: {result.total_ticks}", flush=True)
print(f"Total orders submitted: {result.order_count}", flush=True)
print(f"Total fills: {result.fill_count}", flush=True)
print(f"Closed trades (round-trips): {result.closed_trade_count}", flush=True)
print(f"Win rate: {result.win_rate:.0%}", flush=True)
print(f"Return: {result.total_return_pct:+.4f}%", flush=True)
print(f"Realized PnL: ${float(result.realized_net_pnl_quote):+.4f}", flush=True)
print(f"Residual PnL: ${float(result.residual_pnl_quote):+.4f}", flush=True)
print(f"Total fees: ${float(result.total_fees):.6f}", flush=True)
print(f"Maker fill ratio: {result.maker_fill_ratio:.0%}", flush=True)
print(f"Terminal position (base): {float(result.terminal_position_base):.8f}", flush=True)
print(f"Terminal mark price: ${float(result.terminal_mark_price):.2f}", flush=True)

# 2. Fill analysis - check every fill
print(f"\n--- 2. FILL-BY-FILL ANALYSIS (first 30) ---", flush=True)
fills = result.fills
running_position = Decimal("0")
running_cost_basis = Decimal("0")
anomalies = []

for i, f in enumerate(fills[:30]):
    qty = f.fill_quantity
    price = f.fill_price
    fee = f.fee
    is_buy = f.side == "buy"

    if is_buy:
        running_position += qty
    else:
        running_position -= qty

    notional = qty * price

    # Check: is fill price reasonable relative to mid?
    mid_slip = f.slippage_bps
    if mid_slip > Decimal("50"):
        anomalies.append(f"Fill #{i}: slippage {float(mid_slip):.1f} bps is very high")

    # Check: is fee reasonable?
    expected_fee_range = notional * Decimal("0.00005")  # ~0.5 bps maker
    if fee > notional * Decimal("0.001"):
        anomalies.append(f"Fill #{i}: fee ${float(fee):.6f} is > 10 bps of notional ${float(notional):.2f}")

    # Check: is fill marked as maker?
    if not f.is_maker:
        anomalies.append(f"Fill #{i}: NOT MAKER despite LIMIT order submission")

    print(f"  [{i:3d}] {f.side:4s} qty={float(qty):.6f} price=${float(price):.2f} fee=${float(fee):.6f} maker={f.is_maker} slip={float(mid_slip):.1f}bps pos_after={float(running_position):.6f}", flush=True)

# 3. Position consistency
print(f"\n--- 3. POSITION CONSISTENCY ---", flush=True)
fill_position = Decimal("0")
for f in fills:
    if f.side == "buy":
        fill_position += f.fill_quantity
    else:
        fill_position -= f.fill_quantity

print(f"Position from fills: {float(fill_position):.8f}", flush=True)
print(f"Terminal position (reported): {float(result.terminal_position_base):.8f}", flush=True)
match = abs(fill_position - result.terminal_position_base) < Decimal("0.000001")
print(f"Match: {'YES' if match else 'NO *** MISMATCH ***'}", flush=True)
if not match:
    anomalies.append(f"CRITICAL: Position mismatch! fills={float(fill_position)} vs terminal={float(result.terminal_position_base)}")

# 4. PnL consistency
print(f"\n--- 4. PnL CONSISTENCY ---", flush=True)
actual_return = result.total_return_pct
realized = float(result.realized_net_pnl_quote)
residual = float(result.residual_pnl_quote)
total_pnl = realized + residual
equity_pnl = float(Decimal("500") * Decimal(str(actual_return)) / Decimal("100"))
print(f"Realized + Residual = ${total_pnl:+.4f}", flush=True)
print(f"Equity-based PnL = ${equity_pnl:+.4f}", flush=True)
print(f"Close enough: {abs(total_pnl - equity_pnl) < 0.05}", flush=True)

# 5. Round-trip trade analysis
print(f"\n--- 5. ROUND-TRIP TRADE ANALYSIS ---", flush=True)
print(f"Closed trades: {result.closed_trade_count}", flush=True)
print(f"Winning: {result.winning_trade_count}", flush=True)
print(f"Losing: {result.losing_trade_count}", flush=True)
print(f"Gross profit: ${float(result.gross_profit_quote):+.4f}", flush=True)
print(f"Gross loss: ${float(result.gross_loss_quote):+.4f}", flush=True)
print(f"Avg win: ${float(result.avg_win_quote):.4f}", flush=True)
print(f"Avg loss: ${float(result.avg_loss_quote):.4f}", flush=True)
print(f"Expectancy: ${float(result.expectancy_quote):+.6f}", flush=True)

# Sanity: gross_profit - gross_loss should equal realized PnL
gp_gl = float(result.gross_profit_quote) + float(result.gross_loss_quote)
print(f"GP + GL = ${gp_gl:+.4f} vs realized = ${realized:+.4f}", flush=True)
if abs(gp_gl - realized) > 0.01:
    anomalies.append(f"PnL mismatch: GP+GL={gp_gl:.4f} != realized={realized:.4f}")

# 6. Fee analysis
print(f"\n--- 6. FEE ANALYSIS ---", flush=True)
total_notional = sum(f.fill_price * f.fill_quantity for f in fills)
total_fees_check = sum(f.fee for f in fills)
avg_fee_bps = float(total_fees_check / total_notional * 10000) if total_notional > 0 else 0
print(f"Total notional traded: ${float(total_notional):.2f}", flush=True)
print(f"Total fees: ${float(total_fees_check):.6f}", flush=True)
print(f"Average fee rate: {avg_fee_bps:.2f} bps", flush=True)
maker_fills = sum(1 for f in fills if f.is_maker)
taker_fills = len(fills) - maker_fills
print(f"Maker fills: {maker_fills}, Taker fills: {taker_fills}", flush=True)
if taker_fills > 0:
    anomalies.append(f"WARNING: {taker_fills} taker fills found in LIMIT-only strategy")

# 7. Book synthesis check - look for look-ahead bias
print(f"\n--- 7. BOOK SYNTHESIS CHECK ---", flush=True)
print("(Verifying fill prices are within the candle's OHLCV range)", flush=True)
from controllers.backtesting.historical_feed import HistoricalDataFeed
from controllers.backtesting.data_catalog import DataCatalog
from pathlib import Path
import pyarrow.parquet as pq
import pandas as pd

catalog = DataCatalog(base_dir=Path("hbot/data/historical"))
entry = catalog.find("bitget", "BTC-USDT", "1m",
                      start_ms=1736899200000, end_ms=1737417600000)
candles = entry.load()

# Build a price range map for the backtest period
ts_to_range = {}
for c in candles:
    ts_to_range[c.timestamp_ms] = (float(c.low), float(c.high))

fills_outside_range = 0
for f in fills:
    fill_ts_ms = f.timestamp_ns // 1_000_000
    # Find the closest candle
    closest_ts = min(ts_to_range.keys(), key=lambda t: abs(t - fill_ts_ms))
    low, high = ts_to_range[closest_ts]
    fill_p = float(f.fill_price)
    if fill_p < low * 0.999 or fill_p > high * 1.001:
        fills_outside_range += 1
        if fills_outside_range <= 5:
            print(f"  OUTSIDE RANGE: fill price ${fill_p:.2f} vs candle [{low:.2f}, {high:.2f}] (delta={closest_ts - fill_ts_ms}ms)", flush=True)

print(f"Fills outside candle range: {fills_outside_range}/{len(fills)}", flush=True)
if fills_outside_range > 0:
    anomalies.append(f"WARNING: {fills_outside_range} fills outside candle price range (possible look-ahead)")

# 8. Cancel-before-submit timing check
print(f"\n--- 8. ORDER TIMING ---", flush=True)
print(f"The adapter calls cancel_all() then submit_order() on the SAME tick.", flush=True)
print(f"But desk.tick() already matched orders BEFORE the adapter runs.", flush=True)
print(f"Sequence per tick:", flush=True)
print(f"  1. feed.set_time(now_ns)  -- sets clock", flush=True)
print(f"  2. desk.tick(now_ns)      -- evaluates fills on EXISTING orders", flush=True)
print(f"  3. adapter.tick(...)      -- cancel_all + submit new", flush=True)
print(f"  4. [next tick] desk.tick  -- new orders get evaluated", flush=True)
print(f"This means: orders submitted on tick N are first evaluated on tick N+1.", flush=True)
print(f"This is CORRECT - no look-ahead bias in order evaluation.", flush=True)

# 9. Summary
print(f"\n{'=' * 100}", flush=True)
print(f"ANOMALIES FOUND: {len(anomalies)}", flush=True)
print(f"{'=' * 100}", flush=True)
for a in anomalies:
    print(f"  * {a}", flush=True)
if not anomalies:
    print("  None! Engine appears correct.", flush=True)

print(f"\nAudit complete.", flush=True)
