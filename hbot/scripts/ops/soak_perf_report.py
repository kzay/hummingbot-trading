"""Quick paper soak performance report — reads fills.csv and daily_state.json."""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

BOT = "bot1"
VARIANT = "a"
LOG_ROOT = Path(f"/home/hummingbot/logs/epp_v24/{BOT}_{VARIANT}")

fills_path = LOG_ROOT / "fills.csv"
state_path = LOG_ROOT / "daily_state.json"

# --- Load fills ---
rows = []
with open(fills_path) as f:
    for row in csv.DictReader(f):
        rows.append(row)

if not rows:
    print("No fills found.")
    sys.exit(0)

# --- Load daily state ---
state = {}
if state_path.exists():
    with open(state_path) as f:
        state = json.load(f)

# --- Compute metrics ---
buys  = [r for r in rows if r["side"] == "buy"]
sells = [r for r in rows if r["side"] == "sell"]
makers = [r for r in rows if r.get("is_maker", "").lower() == "true"]
takers = [r for r in rows if r.get("is_maker", "").lower() == "false"]

total_vol  = sum(float(r["notional_quote"]) for r in rows)
total_fee  = sum(float(r["fee_quote"]) for r in rows)
pnl_vals   = [float(r["realized_pnl_quote"]) for r in rows
               if r.get("realized_pnl_quote", "0") not in ("0", "")]
total_pnl  = sum(pnl_vals)

first_ts = datetime.fromisoformat(rows[0]["ts"][:19])
last_ts  = datetime.fromisoformat(rows[-1]["ts"][:19])
hours    = max((last_ts - first_ts).total_seconds() / 3600, 0.001)
fills_hr = len(rows) / hours

equity_open = float(state.get("equity_open", 0))
traded_x    = float(state.get("traded_notional", 0)) / equity_open if equity_open else 0

print()
print("=" * 52)
print("  Bot1 Bitget Paper Soak — Performance Report")
print("=" * 52)
print(f"  Session          : {first_ts.strftime('%H:%M')} → {last_ts.strftime('%H:%M')} UTC  ({hours:.1f}h)")
print(f"  Total fills      : {len(rows):>6}  ({fills_hr:.1f}/hr)")
print(f"    Buys           : {len(buys):>6}")
print(f"    Sells          : {len(sells):>6}")
print(f"    Makers         : {len(makers):>6}  ({len(makers)/len(rows)*100:.0f}%)")
print(f"    Takers         : {len(takers):>6}  ({len(takers)/len(rows)*100:.0f}%)")
print()
print(f"  Total volume     : {total_vol:>10,.2f} USDT")
print(f"  Avg fill size    : {total_vol/len(rows):>10.2f} USDT")
print(f"  Turnover         : {traded_x:>10.3f}x  (target < 3x)")
print()
print(f"  Total fees paid  : {total_fee:>10.4f} USDT")
print(f"  Fee rate         : {total_fee/total_vol*100:>10.4f}%  (config: 0.10%)")
print(f"  Realized PnL     : {total_pnl:>10.4f} USDT")
print(f"  PnL / volume     : {total_pnl/total_vol*10000:>10.2f} bps")
print(f"  PnL / equity     : {total_pnl/equity_open*100:>10.4f}%")
print()
daily_pnl = float(state.get("realized_pnl", 0))
print(f"  Daily state PnL  : {daily_pnl:>10.4f} USDT  (with cost basis)")
pos_base  = float(state.get("position_base", 0))
avg_entry = float(state.get("avg_entry_price", 0))
print(f"  Open position    : {pos_base:.6f} BTC @ ${avg_entry:,.2f}")
print()
# Quick assessment
fee_rate_actual = total_fee / total_vol * 100
if fee_rate_actual > 0.12:
    fee_flag = "⚠  taker fill ratio high"
else:
    fee_flag = "✓  fee rate within config"
print(f"  Assessment       : {fee_flag}")
if daily_pnl < -5:
    pnl_flag = "⚠  PnL below -$5 — check spread floor calibration"
elif daily_pnl < 0:
    pnl_flag = "~  PnL slightly negative — normal for early soak"
else:
    pnl_flag = "✓  PnL positive"
print(f"                   : {pnl_flag}")
print("=" * 52)
